"""Lock in the facts week 1 established, so a refactor cannot silently undo them.

These are offline tests. Network-dependent checks (label agreement, coverage)
belong in the census gate, not the unit suite.
"""

import numpy as np
import pytest

from chira.calibration import (
    brier,
    cox_slope_intercept,
    ece,
    equal_count_bins,
    max_bin_dev,
    murphy,
    simulate_null,
)
from chira.constants import (
    COMPLEMENTARITY_TOL,
    GATE_ECE_MAX,
    GATE_INTERCEPT_BAND,
    GATE_MAX_BIN_DEV,
    GATE_SLOPE_BAND,
    SLUG_DATE_CONVENTIONS,
    USABLE_SEASONS,
)
from chira.schedule import slug, slug_candidates


class TestSlugConventions:
    def test_two_date_candidates_are_emitted(self):
        """Regression: probing ET only loses ~12% of early-2025-26 games."""
        g = {"away": "was", "home": "okc", "et_date": "2025-10-30"}
        cands = slug_candidates("nba", g)
        assert len(cands) == 2
        assert cands[0] == ("et", "nba-was-okc-2025-10-30")
        assert cands[1] == ("et_plus_1", "nba-was-okc-2025-10-31")

    def test_et_plus_1_case_is_real(self):
        """nba-was-okc resolves at 2025-10-31, not the schedule's 2025-10-30."""
        g = {"away": "was", "home": "okc", "et_date": "2025-10-30"}
        assert "nba-was-okc-2025-10-31" in [s for _, s in slug_candidates("nba", g)]

    def test_slug_helper_returns_primary_candidate(self):
        g = {"away": "mem", "home": "sac", "et_date": "2025-11-30"}
        assert slug("nba", g) == "nba-mem-sac-2025-11-30"

    def test_abbr_map_translates_when_supplied(self):
        g = {"away": "no", "home": "lal", "et_date": "2023-12-07"}
        out = slug("nba", g, {"no": "nop"})
        assert out == "nba-nop-lal-2023-12-07"

    def test_conventions_constant_matches_implementation(self):
        g = {"away": "a", "home": "b", "et_date": "2025-01-01"}
        assert tuple(c for c, _ in slug_candidates("nba", g)) == SLUG_DATE_CONVENTIONS

    def test_2023_24_is_excluded(self):
        """Dead markets ($0 volume). Must not be silently re-added."""
        assert "2023-24" not in USABLE_SEASONS
        assert USABLE_SEASONS == ("2024-25", "2025-26")


class TestCalibrationMath:
    @pytest.fixture
    def calibrated(self):
        rng = np.random.default_rng(0)
        p = rng.uniform(0.1, 0.9, 4000)
        y = (rng.random(4000) < p).astype(float)
        return p, y

    def test_murphy_reconciles_with_direct_brier(self, calibrated):
        """Self-consistency only. This does NOT catch a p/y misalignment.

        The decomposition is computed entirely from binned output, so the
        identity holds under any permutation of y within the sorted order.
        Measured: correct residual -3.57e-4 vs misaligned -3.99e-4, against the
        old 2e-3 tolerance. The alignment check is the separate test below.
        """
        p, y = calibrated
        m = murphy(p, y)
        assert m["brier_from_decomp"] == pytest.approx(m["brier_direct"], abs=2e-3)

    def test_reliability_detects_gross_label_misalignment(self, calibrated):
        """Reliability catches a GROSS misalignment. The decomposition residual never does."""
        p, y = calibrated
        order = np.argsort(p, kind="stable")
        ps, ys = p[order], y[order]
        good = murphy(ps, ys)
        bad = murphy(ps, ys[::-1])  # outcomes reversed against price rank
        assert bad["reliability"] > good["reliability"] * 10
        assert ece(ps, ys[::-1]) > ece(ps, ys) * 5

    def test_a_one_index_roll_is_NOT_detectable_and_that_is_the_point(self, calibrated):
        """Records the real limitation, so nobody trusts a binned metric to find it.

        With 4,000 points in 10 equal-count bins, rolling y by one index moves a
        single element per bin. Measured residuals: correct -3.57e-4, rolled
        -3.99e-4. No binned statistic separates those. The defence against an
        off-by-one is the label-agreement assert against nba_api, not this.
        """
        p, y = calibrated
        order = np.argsort(p, kind="stable")
        ps, ys = p[order], y[order]
        assert abs(ece(ps, np.roll(ys, 1)) - ece(ps, ys)) < 5e-3

    def test_equal_count_bins_are_equal_count(self, calibrated):
        p, y = calibrated
        _, _, ns = equal_count_bins(p, y, n_bins=10)
        assert ns.max() - ns.min() <= 1
        assert ns.sum() == len(p)

    def test_perfect_calibration_gives_slope_near_one(self, calibrated):
        p, y = calibrated
        b, a = cox_slope_intercept(p, y)
        assert b == pytest.approx(1.0, abs=0.15)
        assert a == pytest.approx(0.0, abs=0.10)

    def test_deliberate_tilt_is_caught_with_correct_sign(self):
        """Hostile-QA: a miscalibrated market must be detected, not smoothed over."""
        rng = np.random.default_rng(1)
        p = rng.uniform(0.1, 0.9, 6000)
        # outcomes generated from a SHRUNK probability => quoted p is overconfident
        y = (rng.random(6000) < (0.5 + 0.6 * (p - 0.5))).astype(float)
        b, _ = cox_slope_intercept(p, y)
        assert b < 0.9, "overconfident market must yield slope below 1"
        assert ece(p, y) > 0.02

    def test_ece_is_zero_for_a_perfectly_matched_sample(self):
        p = np.repeat([0.25, 0.75], 200)
        y = np.concatenate([np.repeat([1.0, 0.0], [50, 150]),
                            np.repeat([1.0, 0.0], [150, 50])])
        assert ece(p, y, n_bins=2) == pytest.approx(0.0, abs=1e-9)

    def test_brier_hits_its_true_bounds(self):
        assert brier(np.ones(10), np.zeros(10)) == pytest.approx(1.0)
        assert brier(np.ones(10), np.ones(10)) == pytest.approx(0.0)

    def test_brier_of_a_calibrated_market_beats_climatology(self, calibrated):
        p, y = calibrated
        assert brier(p, y) < brier(np.full_like(p, y.mean()), y)


class TestNoiseFloorIsRespected:
    """Every adopted gate must sit at or ABOVE the simulated null.

    Rounding a gate INWARD from the null re-creates the exact false-fire defect
    the simulation existed to remove, so these assert against the real adopted
    constants rather than against unrelated literals.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def null(cls):
        rng = np.random.default_rng(5)
        pool = rng.uniform(0.1, 0.9, 500)
        return simulate_null(pool, n=5084, reps=400, seed=3)

    def test_adopted_ece_gate_does_not_false_fire(self, null):
        assert null["ece"]["p99"] <= GATE_ECE_MAX, (
            f"adopted ECE gate {GATE_ECE_MAX} is below the null p99 "
            f"{null['ece']['p99']:.4f} and would reject a correct pipeline"
        )

    def test_adopted_max_bin_dev_gate_does_not_false_fire(self, null):
        assert null["max_bin_dev"]["p99"] <= GATE_MAX_BIN_DEV

    def test_adopted_slope_band_contains_the_null_ci(self, null):
        lo, hi = GATE_SLOPE_BAND
        assert lo <= null["slope"]["lo2.5"] and null["slope"]["hi97.5"] <= hi

    def test_adopted_intercept_band_contains_the_null_ci(self, null):
        lo, hi = GATE_INTERCEPT_BAND
        assert lo <= null["intercept"]["lo2.5"] and null["intercept"]["hi97.5"] <= hi

    def test_the_withdrawn_002_cap_would_have_false_fired(self, null):
        """PREREGISTRATION.md withdrew a 0.02 ECE cap. This records why."""
        assert null["ece"]["p95"] > 0.02


class TestDegenerateInput:
    """A nan metric compared against a gate evaluates False, i.e. it PASSES.

    An empty or fully-filtered stratum must therefore raise, not return nan.
    """

    @pytest.mark.parametrize("fn", [ece, max_bin_dev, brier, murphy, cox_slope_intercept])
    def test_empty_sample_raises_rather_than_returning_nan(self, fn):
        with pytest.raises(ValueError):
            fn(np.array([]), np.array([]))

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            ece(np.array([0.5, 0.6]), np.array([1.0]))

    def test_nan_can_never_silently_pass_a_gate(self):
        assert not (float("nan") <= GATE_ECE_MAX)

    def test_degenerate_cox_fit_raises_instead_of_reporting_a_slope(self):
        """Constant p previously returned slope 165.04 as if it were a result."""
        with pytest.raises(ValueError):
            cox_slope_intercept(np.full(200, 0.6), (np.arange(200) < 120).astype(float))

    def test_metrics_are_deterministic_for_a_fixed_row_order(self):
        """Stable sort => repeatable results for the SAME input order."""
        rng = np.random.default_rng(0)
        p = np.concatenate([np.full(100, 0.5), rng.uniform(0.1, 0.9, 100)])
        y = np.concatenate([np.ones(50), np.zeros(50), (rng.random(100) < 0.5).astype(float)])
        assert ece(p, y) == ece(p.copy(), y.copy())
        assert max_bin_dev(p, y) == max_bin_dev(p.copy(), y.copy())

    def test_heavy_ties_make_binning_input_order_dependent(self):
        """A real constraint on the pipeline, recorded rather than wished away.

        Equal-count bins split tied prices across a bin boundary, and a stable
        sort preserves INPUT order among ties, so permuting the rows changes
        which tied games land in which bin. Measured: ECE 0.367 vs 0.177 on the
        same multiset. Stable sort buys reproducibility, not permutation
        invariance, so the census MUST write rows in a canonical order
        (game_id) before anything is scored.
        """
        rng = np.random.default_rng(0)
        p = np.concatenate([np.full(100, 0.5), rng.uniform(0.1, 0.9, 100)])
        y = np.concatenate([np.ones(50), np.zeros(50), (rng.random(100) < 0.5).astype(float)])
        perm = rng.permutation(len(p))
        assert ece(p, y) != ece(p[perm], y[perm]), (
            "if this ever passes, ties are being handled and the canonical-order "
            "requirement can be relaxed"
        )


class TestComplementarity:
    def test_tolerance_is_tight(self):
        assert COMPLEMENTARITY_TOL <= 1e-6

    def test_violation_detectable(self):
        assert abs((0.585 + 0.415) - 1.0) < COMPLEMENTARITY_TOL
        assert abs((0.585 + 0.500) - 1.0) > COMPLEMENTARITY_TOL
