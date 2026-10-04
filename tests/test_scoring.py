"""Scoring and the nested test (PLAN Phase 5, PREREGISTRATION section 7)."""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from chira.holdout import DEV_SEASON, HOLDOUT_SEASON, HoldoutError
from chira.scoring import (
    EDGE_FLOOR,
    EDGE_TIERS,
    LOG_LOSS_CLIP,
    RELIABILITY_BUCKETS,
    apply_nested,
    clark_west,
    clipped_log_loss,
    cw_terms,
    fit_nested,
    inv_logit,
    logistic_mle,
    logit,
    pooled_nested,
    recalibration_null,
    reliability_buckets,
    risk_tiers,
    rolling_nested,
    score_set,
    stationary_bootstrap_dates,
)


def ids(n, season=DEV_SEASON):
    return [season] * n, [str(i) for i in range(n)]


class TestTheLogisticFit:
    def test_it_recovers_known_coefficients(self):
        rng = np.random.default_rng(0)
        x1 = rng.normal(size=6000)
        p = inv_logit(-0.3 + 1.2 * x1)
        y = (rng.uniform(size=6000) < p).astype(float)
        got = logistic_mle(np.column_stack([np.ones(6000), x1]), y)
        assert got[0] == pytest.approx(-0.3, abs=0.08)
        assert got[1] == pytest.approx(1.2, abs=0.08)

    def test_separable_data_does_not_diverge(self):
        """The Cox fit blew up twice on exactly this; a ridge and a
        backtracking line search keep the coefficient finite."""
        x1 = np.array([-3.0, -2.0, -1.0, 1.0, 2.0, 3.0])
        y = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        got = logistic_mle(np.column_stack([np.ones(6), x1]), y)
        assert np.all(np.isfinite(got))

    def test_it_refuses_a_single_outcome_class(self):
        with pytest.raises(ValueError, match="not identified"):
            logistic_mle(np.column_stack([np.ones(4), np.arange(4.0)]),
                         np.ones(4))

    def test_it_refuses_an_empty_sample(self):
        with pytest.raises(ValueError, match="empty"):
            logistic_mle(np.zeros((0, 2)), np.zeros(0))

    def test_it_refuses_a_shape_mismatch(self):
        with pytest.raises(ValueError, match="does not match"):
            logistic_mle(np.ones((5, 2)), np.ones(4))


class TestScoring:
    def test_the_log_loss_is_clipped(self):
        """One impossible row must not dominate a secondary number."""
        worst = clipped_log_loss(np.array([0.0]), np.array([1.0]))
        assert worst == pytest.approx(-np.log(LOG_LOSS_CLIP[0]))
        assert np.isfinite(worst)

    def test_score_set_reports_the_murphy_identity(self):
        rng = np.random.default_rng(1)
        p = rng.uniform(0.2, 0.8, size=600)
        y = (rng.uniform(size=600) < p).astype(float)
        s = score_set(p, y, seasons=ids(600)[0], game_ids=ids(600)[1])
        assert s.n == 600
        assert s.brier_from_decomp == pytest.approx(
            s.reliability - s.resolution + s.uncertainty, abs=1e-12)

    def test_the_binning_gap_is_carried_not_hidden(self):
        """The decomposition bins at 10, so it reproduces the direct Brier
        only up to within-bin spread. Both numbers are reported."""
        rng = np.random.default_rng(11)
        p = rng.uniform(0.05, 0.95, size=800)
        y = (rng.uniform(size=800) < p).astype(float)
        s = score_set(p, y, seasons=ids(800)[0], game_ids=ids(800)[1])
        assert s.decomp_gap == pytest.approx(s.brier_from_decomp - s.brier)
        assert abs(s.decomp_gap) < 0.02
        assert any("binning gap" in x for x in s.lines())

    def test_scoring_the_sealed_season_is_refused(self):
        p = np.array([0.6, 0.4])
        y = np.array([1.0, 0.0])
        with pytest.raises(HoldoutError, match="sealed holdout"):
            score_set(p, y, seasons=[HOLDOUT_SEASON] * 2, game_ids=["a", "b"])

    def test_scoring_season_less_rows_is_refused(self):
        with pytest.raises(HoldoutError, match="carry no season"):
            score_set(np.array([0.6]), np.array([1.0]), seasons=[None],
                      game_ids=["a"])


class TestClarkWest:
    def test_an_identical_model_gives_exactly_zero(self):
        """Under B == A every adjusted term is identically zero, which is the
        whole point of the MSPE adjustment."""
        rng = np.random.default_rng(2)
        p = rng.uniform(0.2, 0.8, size=200)
        y = (rng.uniform(size=200) < p).astype(float)
        assert np.allclose(cw_terms(y, p, p), 0.0)
        assert clark_west(y, p, p).statistic == 0.0

    def test_the_formula(self):
        y = np.array([1.0])
        a = np.array([0.4])
        b = np.array([0.7])
        want = (1 - 0.4) ** 2 - ((1 - 0.7) ** 2 - (0.4 - 0.7) ** 2)
        assert cw_terms(y, a, b)[0] == pytest.approx(want)

    def test_a_genuinely_better_b_gives_a_positive_statistic(self):
        rng = np.random.default_rng(3)
        x = rng.normal(size=3000)
        truth = inv_logit(0.9 * x)
        y = (rng.uniform(size=3000) < truth).astype(float)
        a = np.full(3000, float(y.mean()))     # base rate only
        cw = clark_west(y, a, truth)
        assert cw.statistic > 3 and cw.p_normal < 0.01

    def test_it_is_one_sided(self):
        rng = np.random.default_rng(4)
        p = rng.uniform(0.3, 0.7, size=500)
        y = (rng.uniform(size=500) < p).astype(float)
        cw = clark_west(y, p, p + 0.0)
        assert 0.0 <= cw.p_normal <= 1.0

    def test_it_refuses_a_single_game(self):
        with pytest.raises(ValueError, match="at least two"):
            clark_west(np.array([1.0]), np.array([0.5]), np.array([0.6]))

    def test_the_date_bootstrap_is_reported_with_its_block_count(self):
        rng = np.random.default_rng(5)
        n = 400
        dates = np.repeat(np.arange(80), 5)
        p = rng.uniform(0.3, 0.7, size=n)
        y = (rng.uniform(size=n) < p).astype(float)
        cw = clark_west(y, p, p, dates=dates, reps=200)
        assert cw.n_dates == 80 and cw.reps == 200
        assert cw.p_bootstrap is not None
        assert any("80 dates" in x for x in cw.lines("x"))


class TestTheStationaryBootstrap:
    def test_every_resample_keeps_same_date_rows_together(self):
        dates = np.array([1, 1, 1, 2, 2, 3])
        rng = np.random.default_rng(0)
        for idx in stationary_bootstrap_dates(dates, reps=20, rng=rng,
                                              mean_block=2):
            picked = dates[idx]
            for d, count in zip(*np.unique(picked, return_counts=True),
                                strict=True):
                assert count % int((dates == d).sum()) == 0

    def test_it_is_deterministic_under_a_seed(self):
        dates = np.repeat(np.arange(10), 2)
        a = stationary_bootstrap_dates(dates, reps=5,
                                       rng=np.random.default_rng(7))
        b = stationary_bootstrap_dates(dates, reps=5,
                                       rng=np.random.default_rng(7))
        assert all(np.array_equal(x, y) for x, y in zip(a, b, strict=True))

    def test_it_refuses_an_empty_date_vector(self):
        with pytest.raises(ValueError, match="no dates"):
            stationary_bootstrap_dates(np.array([]), reps=2,
                                       rng=np.random.default_rng(0))


class TestTheTwoNulls:
    def test_a_perfectly_calibrated_market_recalibrates_to_identity(self):
        rng = np.random.default_rng(6)
        p = rng.uniform(0.15, 0.85, size=8000)
        y = (rng.uniform(size=8000) < p).astype(float)
        _, coef = recalibration_null(p, y, p)
        assert coef[0] == pytest.approx(0.0, abs=0.1)
        assert coef[1] == pytest.approx(1.0, abs=0.1)

    def test_b_literally_nests_the_recalibration(self):
        """Section 7 requires it, or Clark-West does not apply. With every
        feature zero, B collapses onto `a + b*logit(p)`."""
        rng = np.random.default_rng(8)
        p = rng.uniform(0.2, 0.8, size=3000)
        y = (rng.uniform(size=3000) < p).astype(float)
        zeros = np.zeros((3000, 2))
        nf = fit_nested(p, zeros, y, feature_names=("f1", "f2"))
        out = apply_nested(nf, p, zeros)
        assert np.allclose(out["b"], out["recalibrated"], atol=1e-6)

    def test_the_identity_null_is_the_raw_price(self):
        p = np.array([0.3, 0.6])
        nf = fit_nested(np.array([0.3, 0.6, 0.4, 0.7]),
                        np.zeros((4, 1)), np.array([0.0, 1.0, 0.0, 1.0]),
                        feature_names=("f",))
        assert np.array_equal(apply_nested(nf, p, np.zeros((2, 1)))["identity"],
                              p)

    def test_the_fit_reports_its_columns(self):
        nf = fit_nested(np.array([0.3, 0.6, 0.4, 0.7]), np.zeros((4, 1)),
                        np.array([0.0, 1.0, 0.0, 1.0]), feature_names=("f",))
        assert nf.columns == ("intercept", "logit_price", "f")
        assert any("logit_price" in x for x in nf.lines())


class TestReliabilityBuckets:
    """The probability buckets the first version called risk tiers. Kept as an
    exploratory reliability table; section 9's tiers are on the edge."""

    def test_shares_sum_to_one_and_cover_every_game(self):
        rng = np.random.default_rng(9)
        p = rng.uniform(0.05, 0.95, size=900)
        y = (rng.uniform(size=900) < p).astype(float)
        got = reliability_buckets(p, y, reps=100)
        assert sum(t.n for t in got) == 900
        assert sum(t.share for t in got) == pytest.approx(1.0)

    def test_an_empty_bucket_does_not_crash(self):
        got = reliability_buckets(np.full(50, 0.5), np.ones(50), reps=50)
        assert any(t.n == 0 for t in got) and any(t.n == 50 for t in got)

    def test_the_buckets_are_contiguous_and_cover_zero_to_one(self):
        assert RELIABILITY_BUCKETS[0][0] == 0.0 and RELIABILITY_BUCKETS[-1][1] == 1.0
        for (_, hi), (lo, _) in pairwise(RELIABILITY_BUCKETS):
            assert hi == lo


class TestRiskTiersAreSectionNine:
    """PREREGISTRATION section 9: three tiers on |p_model - p_market|."""

    def test_the_bands_are_the_pre_registered_ones(self):
        assert EDGE_FLOOR == 0.02
        assert [(n, lo, hi) for n, lo, hi in EDGE_TIERS] == [
            ("T1", 0.02, 0.05), ("T2", 0.05, 0.10), ("T3", 0.10, None)]

    def test_games_under_the_floor_are_not_tiered(self):
        pm = np.array([0.50, 0.51, 0.53, 0.58, 0.70])
        pk = np.array([0.50, 0.50, 0.50, 0.50, 0.50])
        tiers, untiered = risk_tiers(pm, pk, np.ones(5), reps=20)
        assert untiered == 2
        assert [t.n for t in tiers] == [1, 1, 1]

    def test_the_hit_follows_the_models_side_of_the_disagreement(self):
        """Model above market and home wins: a hit. Model below market and
        home loses: also a hit."""
        pm = np.array([0.65, 0.35, 0.65, 0.35])   # edge 0.15: clear of float
        pk = np.array([0.50, 0.50, 0.50, 0.50])   # rounding at the 0.10 edge
        y = np.array([1.0, 0.0, 0.0, 1.0])
        tiers, _ = risk_tiers(pm, pk, y, reps=20)
        t3 = tiers[2]
        assert t3.n == 4 and t3.hit_rate == pytest.approx(0.5)
        tiers, _ = risk_tiers(pm[:2], pk[:2], y[:2], reps=20)
        assert tiers[2].hit_rate == 1.0

    def test_an_empty_top_tier_is_a_valid_result(self):
        tiers, _ = risk_tiers(np.full(30, 0.53), np.full(30, 0.50),
                              np.ones(30), reps=20)
        assert tiers[2].n == 0 and "empty" in tiers[2].line()

    def test_the_interval_brackets_the_hit_rate(self):
        rng = np.random.default_rng(10)
        pm = rng.uniform(0.55, 0.60, size=400)
        y = (rng.uniform(size=400) < 0.55).astype(float)
        tiers, _ = risk_tiers(pm, np.full(400, 0.50), y, reps=400)
        t = tiers[1]                              # edges 0.05-0.10: T2
        assert t.ci[0] <= t.hit_rate <= t.ci[1]


def _nested_rows(n_days=180, per_day=3, seed=5):
    """Synthetic dev games spanning 2024-10 to 2025-04, with the columns
    build_design needs and a market price that knows the truth a little."""
    from datetime import UTC, datetime, timedelta

    from chira.ratings import MODEL_COVARIATE
    rng = np.random.default_rng(seed)
    teams = ["a", "b", "c", "d", "e", "f"]
    t0 = datetime(2024, 10, 20, 23, 0, tzinfo=UTC)
    rows, prices = [], {}
    for d in range(n_days):
        for k in range(per_day):
            gid = f"g{d}-{k}"
            away, home = rng.choice(teams, size=2, replace=False)
            strength = float(rng.normal())
            y = float(rng.uniform() < inv_logit(0.2 + 0.8 * strength))
            rows.append({
                "sport": "nba", "season": DEV_SEASON, "game_id": gid,
                "away": str(away), "home": str(home), "y": y,
                "start_t": int((t0 + timedelta(days=d)).timestamp()),
                "away_rest_days": 2, "home_rest_days": int(rng.integers(1, 4)),
                "away_b2b": False, "home_b2b": False,
                "away_travel_km": 800.0, "home_travel_km": 600.0,
                "away_tz_shift": 0.0, "home_tz_shift": 0.0,
                MODEL_COVARIATE: 100.0 * strength, "neutral_site": False})
            prices[gid] = float(np.clip(inv_logit(0.2 + 0.5 * strength), 0.05, 0.95))
    return rows, prices


class TestTheNestedTestRunsOutOfSample:
    def test_each_fold_is_scored_only_on_games_after_its_origin(self):
        rows, prices = _nested_rows()
        folds, skipped = rolling_nested(rows, prices, sport="nba")
        assert skipped == []
        start = {r["game_id"]: r["start_t"] for r in rows}
        from chira.model import _epoch
        for f in folds:
            assert all(start[g] >= _epoch(f.origin) for g in f.game_ids)
            assert f.n_train > 0 and f.n_test == len(f.game_ids)

    def test_b_gets_the_models_own_covariates(self):
        from chira.model import FEATURE_TERMS, build_design
        from chira.scoring import nested_design
        rows, _ = _nested_rows(n_days=30)
        x, names = nested_design(build_design(rows, sport="nba"))
        assert names[1:] == FEATURE_TERMS["nba"] and x.shape[1] == len(names)

    def test_pooling_keeps_every_prediction_aligned(self):
        rows, prices = _nested_rows()
        preds, y, gids = pooled_nested(rolling_nested(rows, prices, sport="nba")[0])
        assert {k: v.size for k, v in preds.items()} == {
            "identity": y.size, "recalibrated": y.size, "b": y.size}
        assert len(gids) == y.size

    def test_a_fold_with_no_priced_games_is_skipped_and_named(self):
        """NHL 2024-25 had no market before December: the first origins
        cannot run, and they are reported, not merged into the next fold."""
        rows, prices = _nested_rows()
        from chira.model import _epoch
        cut = _epoch("2024-12-01")
        prices = {g: v for g, v in prices.items()
                  if next(r for r in rows if r["game_id"] == g)["start_t"] >= cut}
        folds, skipped = rolling_nested(rows, prices, sport="nba")
        assert skipped == ["2024-11-01", "2024-12-01"]
        assert folds[0].origin == "2025-01-01"

    def test_a_holdout_row_is_refused(self):
        rows, prices = _nested_rows(n_days=40)
        rows[0]["season"] = HOLDOUT_SEASON
        with pytest.raises(HoldoutError):
            rolling_nested(rows, prices, sport="nba")


def test_logit_round_trips():
    p = np.array([0.1, 0.5, 0.9])
    assert np.allclose(inv_logit(logit(p)), p)


def test_an_unconverged_logistic_fit_raises_instead_of_posing_as_the_mle(
        monkeypatch):
    """Model B and the recalibration null decide the primary test; the first
    version returned the last iterate when it ran out of iterations."""
    import chira.scoring as S

    rng = np.random.default_rng(3)
    x = np.column_stack([np.ones(400), rng.normal(size=400)])
    y = (rng.random(400) < S.inv_logit(0.3 + 1.2 * x[:, 1])).astype(float)
    assert np.isfinite(S.logistic_mle(x, y)).all(), "the premise: it converges"
    monkeypatch.setattr(S, "NEWTON_MAX_ITER", 1)
    with pytest.raises(ValueError, match="did not converge"):
        S.logistic_mle(x, y)
