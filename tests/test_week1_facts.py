"""Lock in the facts week 1 established, so a refactor cannot silently undo them.

These are offline tests. Network-dependent checks (label agreement, coverage)
belong in the census gate, not the unit suite.
"""

import numpy as np
import pytest

from chira.calibration import brier, cox_slope_intercept, ece, equal_count_bins, murphy
from chira.constants import COMPLEMENTARITY_TOL, SLUG_DATE_CONVENTIONS, USABLE_SEASONS
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
        """A silent off-by-one here invalidates every chart."""
        p, y = calibrated
        m = murphy(p, y)
        assert m["brier_from_decomp"] == pytest.approx(m["brier_direct"], abs=2e-3)

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

    def test_brier_bounds(self, calibrated):
        p, y = calibrated
        assert 0.0 <= brier(p, y) <= 0.25 + 1e-9


class TestNoiseFloorIsRespected:
    """The thresholds in PREREGISTRATION.md must sit ABOVE the null p99."""

    def test_adopted_ece_gate_does_not_false_fire(self):
        from chira.calibration import simulate_null
        rng = np.random.default_rng(5)
        pool = rng.uniform(0.1, 0.9, 500)
        null = simulate_null(pool, n=5084, reps=120, seed=3)
        assert null["ece"]["p99"] < 0.05, "sanity: null ECE at full n is small but nonzero"
        assert null["ece"]["p95"] > 0.005, "a 0.02 cap was rejected for being below this"


class TestComplementarity:
    def test_tolerance_is_tight(self):
        assert COMPLEMENTARITY_TOL <= 1e-6

    def test_violation_detectable(self):
        assert abs((0.585 + 0.415) - 1.0) < COMPLEMENTARITY_TOL
        assert abs((0.585 + 0.500) - 1.0) > COMPLEMENTARITY_TOL
