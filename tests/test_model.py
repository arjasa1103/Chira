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
    ROLLING_ORIGINS,
    SENSITIVITY_MULTIPLIERS,
    SENSITIVITY_PARAMS,
    Diagnostics,
    DiagnosticsError,
    SensitivityRow,
    assert_diagnostics,
    build_design,
    derive_terms,
    dev_medians,
    fill_missing,
    fit,
    fold_slices,
    predict,
    prior_driven,
    rolling_origin,
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

    def test_a_prebuilt_holdout_design_cannot_ride_in_on_dev_rows(self):
        """The first `fit` checked `rows` and then sampled whatever `design`
        it was handed, so harmless dev rows plus a design built from 2025-26
        fitted the holdout with every guard green. Rolling-origin folds pass
        prebuilt designs, which is exactly where this path gets used."""
        sealed = build_design(frame(8, season=HOLDOUT_SEASON), sport="nba",
                              dev_rows=frame(8))
        assert sealed.seasons == (HOLDOUT_SEASON,), "the premise"
        with pytest.raises(HoldoutError, match="design"):
            fit(frame(8), sport="nba", design=sealed,
                warmup=2, samples=2, chains=2)


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


def test_a_nan_rhat_fails_the_gate_instead_of_passing_it():
    """`gelman_rubin` returns NaN for a draw with no variance, and NaN > 1.01
    is False, so the first version let an uncheckable parameter through."""
    from chira.model import DiagnosticsError, assert_diagnostics, diagnostics

    class FakeMCMC:
        def get_samples(self, group_by_chain=False):
            return {"alpha": np.random.default_rng(0).normal(size=(4, 200)),
                    "stuck": np.ones((4, 200))}

        def get_extra_fields(self):
            return {"diverging": np.zeros((4, 200), dtype=bool)}

    d = diagnostics(FakeMCMC())
    assert d.worst_param == "stuck"
    with pytest.raises(DiagnosticsError, match="R-hat"):
        assert_diagnostics(d)


class TestPredictingAnUnseenSeason:
    def _fitted(self):
        dev = frame(80)
        d = build_design(dev, sport="nba")
        return fit(dev, sport="nba", warmup=300, samples=300, chains=2,
                   design=d), d, dev

    def test_an_unseen_team_season_is_marginalised_not_zeroed(self):
        f, d_dev, dev = self._fitted()
        new = frame(40, season=HOLDOUT_SEASON)
        d_new = build_design(new, sport="nba", scaler=d_dev.scaler,
                             medians=dev_medians(dev))
        pr = predict(f, d_new, seed=3)
        assert len(pr.unseen_team_seasons) == 4
        assert pr.n_unseen_rows == 40
        # Marginalising an unknown effect must WIDEN the predictive spread.
        assert pr.draws.std(axis=0).mean() > \
            predict(f, d_dev, seed=3).draws.std(axis=0).mean()

    def test_a_seen_team_season_reuses_the_fitted_effect(self):
        f, d_dev, _ = self._fitted()
        assert predict(f, d_dev, seed=1).unseen_team_seasons == ()
        a = predict(f, d_dev, seed=1).p
        b = predict(f, d_dev, seed=2).p
        np.testing.assert_allclose(a, b)   # no randomness when nothing is new

    def test_rescaling_with_the_new_seasons_own_statistics_is_refused(self):
        """The classic leak, and it leaves no trace in the output. The
        medians are passed correctly here so that the SCALER is the only
        thing wrong, which is what the guard is for."""
        f, _, dev = self._fitted()
        own = build_design(frame(40, season=HOLDOUT_SEASON), sport="nba",
                           medians=dev_medians(dev))
        with pytest.raises(ValueError, match="its own statistics"):
            predict(f, own)

    def test_the_report_names_the_unseen_team_seasons(self):
        f, d_dev, dev = self._fitted()
        d_new = build_design(frame(40, season=HOLDOUT_SEASON), sport="nba",
                             scaler=d_dev.scaler, medians=dev_medians(dev))
        assert any("not in the fit" in x
                   for x in predict(f, d_new, seed=0).lines())


class TestTheRollingOriginSlices:
    """Pure slicing, so the contract is checked without six MCMC runs."""

    def rows(self):
        import datetime as dt

        def ep(d):
            return int(dt.datetime.fromisoformat(f"{d}T00:00:00+00:00")
                       .timestamp())
        days = ["2024-10-15", "2024-11-15", "2024-12-15", "2025-01-15",
                "2025-02-15", "2025-03-15", "2025-04-15"]
        return [{"start_t": ep(d), "game_id": f"g{i}"}
                for i, d in enumerate(days)]

    def test_train_grows_and_test_blocks_are_disjoint(self):
        folds = fold_slices(self.rows(), ROLLING_ORIGINS)
        assert len(folds) == len(ROLLING_ORIGINS)
        sizes = [len(tr) for _, _, tr, _ in folds]
        assert sizes == sorted(sizes) and sizes[0] == 1
        seen = [g["game_id"] for _, _, _, te in folds for g in te]
        assert len(seen) == len(set(seen))

    def test_october_is_training_only(self):
        """Amendment 5c says so explicitly."""
        folds = fold_slices(self.rows(), ROLLING_ORIGINS)
        tested = {g["game_id"] for _, _, _, te in folds for g in te}
        assert "g0" not in tested
        assert "g0" in {g["game_id"] for _, _, tr, _ in folds for g in tr}

    def test_the_last_fold_runs_to_the_end_of_the_season(self):
        assert fold_slices(self.rows(), ROLLING_ORIGINS)[-1][1] is None

    def test_no_test_game_starts_before_its_origin(self):
        import datetime as dt
        for origin, _, _, test in fold_slices(self.rows(), ROLLING_ORIGINS):
            lo = int(dt.datetime.fromisoformat(f"{origin}T00:00:00+00:00")
                     .timestamp())
            assert all(g["start_t"] >= lo for g in test)

    def test_an_empty_side_refuses(self):
        with pytest.raises(ValueError, match="not a fold"):
            fold_slices(self.rows(), ("2024-09-01",))

    def test_the_origins_are_the_pre_registered_ones(self):
        assert ROLLING_ORIGINS == ("2024-11-01", "2024-12-01", "2025-01-01",
                                   "2025-02-01", "2025-03-01", "2025-04-01")


def test_rolling_origin_refuses_holdout_rows():
    rows = [*frame(8), row(99, "bos", "nyk", season=HOLDOUT_SEASON)]
    for r in rows:
        r.setdefault("start_t", 0)
    with pytest.raises(HoldoutError, match="sealed holdout"):
        rolling_origin(rows, sport="nba")


class TestHyperpriorSensitivity:
    """PREREGISTRATION section 5: mandatory, reported, never used to
    re-choose. On hierarchical variance parameters the prior can be the
    result, so the point is to show whether it is."""

    def test_prior_driven_flags_a_posterior_that_tracks_its_prior(self):
        rows = [SensitivityRow("tau_team", m, 0.5 * m, 0.1 * m, 0.05, 0.9,
                               Diagnostics(0, 1.0, "a", 900, "a"))
                for m in (0.5, 1.0, 2.0)]
        flagged = prior_driven(rows)
        assert flagged and "prior-driven" in flagged[0]

    def test_a_posterior_that_ignores_its_prior_is_not_flagged(self):
        rows = [SensitivityRow("tau_team", m, 0.5 * m, 0.11, 0.05, 0.9,
                               Diagnostics(0, 1.0, "a", 900, "a"))
                for m in (0.5, 1.0, 2.0)]
        assert prior_driven(rows) == []

    def test_the_tolerance_is_what_decides(self):
        rows = [SensitivityRow("tau_home", m, 0.25 * m, 0.1 + 0.02 * m, 0.05,
                               0.9, Diagnostics(0, 1.0, "a", 900, "a"))
                for m in (0.5, 1.0, 2.0)]
        assert prior_driven(rows, tol=0.5) == []
        assert prior_driven(rows, tol=0.001) != []

    def test_the_grid_brackets_the_adopted_scale_both_ways(self):
        assert min(SENSITIVITY_MULTIPLIERS) < 1.0 < max(SENSITIVITY_MULTIPLIERS)
        assert 1.0 in SENSITIVITY_MULTIPLIERS
        assert set(SENSITIVITY_PARAMS) <= set(PRIORS)

    def test_only_variance_parameters_are_varied(self):
        """Section 5 is specifically about hierarchical variances."""
        assert all(p.startswith("tau_") for p in SENSITIVITY_PARAMS)

    def test_a_zero_posterior_mean_does_not_divide_by_zero(self):
        rows = [SensitivityRow("tau_team", m, 0.5 * m, 0.0, 0.0, 0.9,
                               Diagnostics(0, 1.0, "a", 900, "a"))
                for m in (0.5, 1.0, 2.0)]
        assert prior_driven(rows) == []


def test_predict_refuses_a_design_filled_with_its_own_medians():
    """The docstring promised the medians were checked; only the scaler was.
    A later season filled with its own median leaks like one standardised
    with its own mean."""
    from types import SimpleNamespace

    from chira.model import predict

    dev = frame(40)
    for r in dev[:5]:
        r["away_rest_days"] = None
    d_fit = build_design(dev, sport="nba")
    later = frame(40)
    later[0]["away_rest_days"] = None
    own = dict(d_fit.fill.medians, away_rest_days=d_fit.fill.medians["away_rest_days"] + 1)
    d_new = build_design(later, sport="nba", scaler=d_fit.scaler, medians=own)
    with pytest.raises(ValueError, match="own median"):
        predict(SimpleNamespace(design=d_fit), d_new)
