"""The hierarchical logistic model (PLAN Phase 4).

Offline. The design builder and the guards are pure and get synthetic rows;
one small MCMC smoke test proves the sampler is actually wired, because a
design matrix that never reaches a sampler is not a model.
"""

from __future__ import annotations

import numpy as np

# Imported EAGERLY, at module scope, and never lazily inside a test.
# conftest's `_no_network` fixture replaces `socket.socket` with a plain
# function, and `ssl` does `class SSLSocket(socket)` at import time, so a
# numpyro import that first happens inside a test dies with
# `TypeError: function() argument 'code' must be code, not str` -- which looks
# like a numpyro bug and is not one.
import numpyro  # noqa: F401
import pytest

from chira.holdout import DEV_SEASON, HOLDOUT_SEASON, HoldoutError
from chira.model import (
    FEATURE_TERMS,
    FILLED,
    MAX_RHAT,
    PRIORS,
    Diagnostics,
    DiagnosticsError,
    assert_diagnostics,
    build_design,
    derive_terms,
    dev_medians,
    fill_missing,
    fit,
    standardise,
)
from chira.ratings import MODEL_COVARIATE


def row(gid, away, home, *, sport="nba", season=DEV_SEASON, y=1.0,
        rest_a=2, rest_h=2, b2b_a=False, b2b_h=False, trav_a=1000.0,
        trav_h=1000.0, tz_a=0.0, tz_h=0.0, rating=50.0, neutral=False):
    return {"sport": sport, "season": season, "game_id": str(gid),
            "away": away, "home": home, "y": y,
            "away_rest_days": rest_a, "home_rest_days": rest_h,
            "away_b2b": b2b_a, "home_b2b": b2b_h,
            "away_travel_km": trav_a, "home_travel_km": trav_h,
            "away_tz_shift": tz_a, "home_tz_shift": tz_h,
            MODEL_COVARIATE: rating, "neutral_site": neutral}


def frame(n=40, sport="nba", season=DEV_SEASON):
    teams = ["bos", "nyk", "lal", "phi"] if sport == "nba" else \
            ["bos", "nyr", "tor", "phi"]
    out = []
    for i in range(n):
        a, h = teams[i % 4], teams[(i + 1) % 4]
        out.append(row(i, a, h, sport=sport, season=season,
                       y=float(i % 2), rating=float(i * 3 - 60)))
    return out


class TestTheFeatureTerms:
    def test_amendment_5a_gives_the_nhl_two_b2b_terms_and_the_nba_one(self):
        assert FEATURE_TERMS["nba"].count("b2b_diff") == 1
        assert "home_b2b" not in FEATURE_TERMS["nba"]
        assert "home_b2b" in FEATURE_TERMS["nhl"]
        assert "away_b2b" in FEATURE_TERMS["nhl"]
        assert "b2b_diff" not in FEATURE_TERMS["nhl"]

    def test_no_price_term_exists(self):
        """Headline 1 is a price-free model."""
        for terms in FEATURE_TERMS.values():
            assert not [t for t in terms if "price" in t or t.startswith("p_")]

    def test_prior_win_rate_is_not_a_term(self):
        """Phase 3 builds it, Phase 4 does not list it, and the Elo is this
        project's prior-results feature."""
        for terms in FEATURE_TERMS.values():
            assert not [t for t in terms if "win_rate" in t]

    def test_the_rating_covariate_excludes_the_home_bonus(self):
        assert MODEL_COVARIATE == "rating_diff_strength"


class TestDerivedTerms:
    def test_the_differences_are_home_minus_away(self):
        got = derive_terms([row(1, "bos", "nyk", rest_a=1, rest_h=3,
                                trav_a=100.0, trav_h=400.0,
                                tz_a=-1.0, tz_h=2.0)])[0]
        assert got["rest_diff"] == 2
        assert got["travel_diff"] == 300.0
        assert got["tz_diff"] == 3.0

    def test_b2b_booleans_become_numbers(self):
        got = derive_terms([row(1, "bos", "nyk", b2b_a=True, b2b_h=False)])[0]
        assert got["away_b2b"] == 1.0 and got["home_b2b"] == 0.0
        assert got["b2b_diff"] == -1.0


class TestTheMedianFill:
    def test_it_counts_every_substitution(self):
        rows = [row(1, "bos", "nyk"), row(2, "bos", "nyk", rest_a=None)]
        filled, report = fill_missing(rows, {c: 7.0 for c in FILLED})
        assert report.counts["away_rest_days"] == 1
        assert filled[1]["away_rest_days"] == 7.0
        assert any("away_rest_days: 1 filled" in x for x in report.lines())

    def test_nothing_filled_is_said_so(self):
        _, report = fill_missing([row(1, "bos", "nyk")],
                                 {c: 7.0 for c in FILLED})
        assert any("nothing filled" in x for x in report.lines())

    def test_the_median_comes_from_dev_rows_only(self):
        rows = [row(1, "bos", "nyk", rest_a=2),
                row(2, "bos", "nyk", rest_a=4),
                row(3, "bos", "nyk", rest_a=100, season=HOLDOUT_SEASON)]
        assert dev_medians(rows)["away_rest_days"] == 3.0

    def test_a_column_with_no_dev_value_refuses(self):
        rows = [row(1, "bos", "nyk", rest_a=None)]
        with pytest.raises(ValueError, match="no dev values"):
            dev_medians(rows)

    def test_a_holdout_frame_is_filled_with_dev_medians(self):
        dev = frame(8)
        med = dev_medians(dev)
        hold = [row(99, "bos", "nyk", season=HOLDOUT_SEASON, rest_a=None)]
        filled, _ = fill_missing(hold, med)
        assert filled[0]["away_rest_days"] == med["away_rest_days"]


class TestStandardise:
    def test_it_centres_and_scales(self):
        z, stats = standardise(np.array([1.0, 3.0, 5.0]))
        assert z.mean() == pytest.approx(0.0)
        assert stats == (3.0, pytest.approx(np.std([1.0, 3.0, 5.0])))

    def test_frozen_stats_are_reused_not_recomputed(self):
        z, stats = standardise(np.array([10.0, 20.0]), (0.0, 1.0))
        assert stats == (0.0, 1.0)
        assert list(z) == [10.0, 20.0]

    def test_a_constant_column_does_not_divide_by_zero(self):
        z, stats = standardise(np.array([4.0, 4.0, 4.0]))
        assert stats[1] == 1.0
        assert not np.isnan(z).any()


class TestTheDesign:
    def test_shapes_and_indices(self):
        d = build_design(frame(40), sport="nba")
        assert d.n == 40
        assert d.features.shape == (40, len(FEATURE_TERMS["nba"]))
        assert d.n_team_seasons == 4
        assert d.home_idx.max() < d.n_team_seasons
        assert set(d.y) <= {0.0, 1.0}

    def test_team_seasons_are_keyed_by_season(self):
        rows = [*frame(8), *frame(8, season=HOLDOUT_SEASON)]
        d = build_design(rows, sport="nba", dev_rows=frame(8))
        assert d.n_team_seasons == 8
        assert any(k.startswith(f"{HOLDOUT_SEASON}:") for k in d.team_seasons)

    def test_a_neutral_game_switches_the_home_term_off(self):
        d = build_design([row(1, "bos", "nyk", neutral=True),
                          row(2, "bos", "nyk")], sport="nba")
        assert sorted(d.not_neutral) == [0.0, 1.0]

    def test_it_refuses_a_sport_with_no_rows(self):
        with pytest.raises(ValueError, match="no nhl rows"):
            build_design(frame(8), sport="nhl")

    def test_the_scaler_can_be_frozen_and_reused(self):
        dev = frame(40)
        d1 = build_design(dev, sport="nba")
        d2 = build_design(frame(40, season=HOLDOUT_SEASON), sport="nba",
                          scaler=d1.scaler, medians=dev_medians(dev))
        assert d2.scaler[MODEL_COVARIATE] == d1.scaler[MODEL_COVARIATE]

    def test_the_nhl_design_carries_both_b2b_columns(self):
        d = build_design(frame(20, sport="nhl"), sport="nhl")
        assert d.feature_names == FEATURE_TERMS["nhl"]
        assert d.features.shape[1] == 5


class TestDiagnosticsAreHardFailures:
    """PREREGISTRATION section 5 (T5)."""

    def test_a_clean_run_passes(self):
        assert assert_diagnostics(
            Diagnostics(0, 1.001, "alpha", 900, "alpha")) is None

    def test_one_divergence_raises(self):
        with pytest.raises(DiagnosticsError, match="1 divergent"):
            assert_diagnostics(Diagnostics(1, 1.0, "alpha", 900, "alpha"))

    def test_an_rhat_above_the_threshold_raises(self):
        with pytest.raises(DiagnosticsError, match="R-hat"):
            assert_diagnostics(
                Diagnostics(0, MAX_RHAT + 1e-6, "tau_team", 900, "alpha"))

    def test_the_threshold_itself_is_allowed(self):
        assert assert_diagnostics(
            Diagnostics(0, MAX_RHAT, "tau_team", 900, "alpha")) is None

    def test_both_problems_are_reported_together(self):
        with pytest.raises(DiagnosticsError) as e:
            assert_diagnostics(Diagnostics(3, 1.2, "tau_team", 10, "alpha"))
        assert "3 divergent" in str(e.value) and "R-hat" in str(e.value)


class TestTheFitRefusesTheHoldout:
    def test_a_holdout_row_stops_it_before_any_sample_is_drawn(self):
        rows = [*frame(8), row(99, "bos", "nyk", season=HOLDOUT_SEASON)]
        with pytest.raises(HoldoutError, match="sealed holdout"):
            fit(rows, sport="nba", warmup=2, samples=2, chains=2)

    def test_a_season_less_row_also_stops_it(self):
        bad = row(99, "bos", "nyk")
        del bad["season"]
        with pytest.raises(HoldoutError, match="carry no season"):
            fit([*frame(8), bad], sport="nba", warmup=2, samples=2, chains=2)


def test_a_single_chain_run_cannot_pass_the_rhat_gate():
    """R-hat is a between-chain statistic; one chain would give NaN, and NaN
    sails through a `>` comparison."""
    with pytest.raises(DiagnosticsError, match="R-hat needs at least"):
        fit(frame(40), sport="nba", warmup=20, samples=20, chains=1)


def test_the_sampler_actually_runs_and_returns_probabilities():
    """A smoke test: a design matrix that never reaches a sampler is not a
    model. Tiny on purpose -- convergence is checked on the real fit."""
    f = fit(frame(60), sport="nba", warmup=150, samples=150, chains=2, seed=1)
    p = f.p_home()
    assert p.shape == (60,)
    assert (p > 0).all() and (p < 1).all()
    assert f.diag.divergences >= 0
    assert set(f.priors) == set(PRIORS)
