"""T10 / E8 — the hostile-QA synthetic-market test of the scorer.

The instrument judges a real-money market, and nothing had ever validated the
instrument itself. Every test here feeds the scorer a market whose true
calibration is known BY CONSTRUCTION and asserts the scorer's verdict, in both
directions:

- a perfectly calibrated market must score near zero miscalibration, and
- a deliberately tilted one must be caught WITH THE CORRECT SIGN.

The sign half is the part that matters. A scorer that flags every market as
miscalibrated passes the first half and is useless; one that reports the tilt
backwards would invert headline 2's conclusion while looking like a finding.

Construction: outcomes are drawn from the TRUE probability, and the market
reports `expit(k * logit(p_true)) + shift`. Then k > 1 is an overconfident
market (prices too extreme), whose Cox slope must come back at ~1/k < 1.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.special import expit, logit

from chira.calibration import (
    MAX_BINS,
    bootstrap_scalars,
    brier,
    cox_slope_intercept,
    ece,
    murphy,
)
from chira.constants import GATE_ECE_MAX, GATE_INTERCEPT_BAND, GATE_SLOPE_BAND

# The census's real shape: 4,661 priced games, NBA prices spread over roughly
# 0.05-0.98. Using the real n keeps "near zero" meaning what it means at the n
# the verdict will actually be quoted at.
CENSUS_N = 4661


def synthetic_market(n=CENSUS_N, *, k=1.0, shift=0.0, seed=0, lo=0.05, hi=0.95):
    """(p_market, y). k=1 and shift=0 is perfectly calibrated."""
    rng = np.random.default_rng(seed)
    p_true = rng.uniform(lo, hi, n)
    y = (rng.random(n) < p_true).astype(float)
    p_mkt = np.clip(expit(k * logit(p_true)) + shift, 1e-4, 1 - 1e-4)
    return p_mkt, y


class TestPerfectlyCalibratedScoresNearZero:
    """The false-fire half: a correct market must not be called broken."""

    @pytest.fixture(scope="class")
    @classmethod
    def perfect(cls):
        return synthetic_market(seed=11)

    def test_ece_is_inside_the_adopted_gate(self, perfect):
        p, y = perfect
        assert ece(p, y, MAX_BINS) <= GATE_ECE_MAX

    def test_cox_slope_and_intercept_land_near_identity(self, perfect):
        p, y = perfect
        slope, intercept = cox_slope_intercept(p, y)
        assert slope == pytest.approx(1.0, abs=0.08)
        assert intercept == pytest.approx(0.0, abs=0.07)

    def test_bootstrap_cis_are_tight_around_identity(self, perfect):
        """The EQUIVALENCE form of PREREGISTRATION.md section 4, in shape only.

        Deliberately NOT asserted against GATE_SLOPE_BAND / GATE_INTERCEPT_BAND.
        Those constants were derived from the census's own price pool, and this
        market is drawn from uniform(0.05, 0.95), which has a different spread
        in logit space and therefore a different null width. Borrowing the
        census bound for a synthetic pool measures the mismatch between two
        pools, not the scorer. `scripts/derive_null_bands.py` is what compares
        the constants to the pool they govern.
        """
        p, y = perfect
        s = bootstrap_scalars(p, y, reps=600, seed=3)
        assert s["slope"]["lo"] <= 1.0 <= s["slope"]["hi"]
        assert s["intercept"]["lo"] <= 0.0 <= s["intercept"]["hi"]
        assert s["slope"]["hi"] - s["slope"]["lo"] < 0.25, "CI implausibly wide at n=4661"
        assert s["cox_failures"] == 0

    def test_murphy_reconciles_with_the_direct_brier(self, perfect):
        p, y = perfect
        m = murphy(p, y, MAX_BINS)
        assert m["brier_from_decomp"] == pytest.approx(m["brier_direct"], abs=5e-3)

    @pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
    def test_it_does_not_false_fire_across_seeds(self, seed):
        """Specificity. A scorer that flags everything passes every other test."""
        p, y = synthetic_market(seed=seed)
        assert ece(p, y, MAX_BINS) <= GATE_ECE_MAX


class TestTiltIsCaughtWithTheCorrectSign:
    def test_overconfident_market_gives_slope_below_one(self):
        """Prices too extreme => the truth is less extreme => slope < 1."""
        p, y = synthetic_market(k=1.25, seed=5)
        slope, _ = cox_slope_intercept(p, y)
        assert slope < 1.0
        assert slope == pytest.approx(1 / 1.25, abs=0.12)
        assert slope < GATE_SLOPE_BAND[0], "a 25% overconfident market must be caught"

    def test_underconfident_market_gives_slope_above_one(self):
        """Prices shrunk toward 0.5 => slope > 1. The opposite sign."""
        p, y = synthetic_market(k=0.8, seed=5)
        slope, _ = cox_slope_intercept(p, y)
        assert slope > 1.0
        assert slope == pytest.approx(1 / 0.8, abs=0.15)
        assert slope > GATE_SLOPE_BAND[1], "a 20% underconfident market must be caught"

    def test_the_two_tilts_are_ordered(self):
        """The sign is not an artifact of one threshold's placement."""
        over, _ = cox_slope_intercept(*synthetic_market(k=1.25, seed=5))
        under, _ = cox_slope_intercept(*synthetic_market(k=0.8, seed=5))
        assert over < 1.0 < under

    def test_a_shifted_market_moves_the_intercept(self):
        p, y = synthetic_market(shift=0.05, seed=7)
        _, intercept = cox_slope_intercept(p, y)
        assert intercept < GATE_INTERCEPT_BAND[0], (
            "a market 5 points long the home side must show a negative intercept: "
            "quoted prices exceed the observed rate"
        )

    def test_tilt_raises_ece_above_the_gate(self):
        p, y = synthetic_market(k=1.4, seed=9)
        assert ece(p, y, MAX_BINS) > GATE_ECE_MAX

    def test_orientation_flip_is_caught(self):
        """The failure mode that does not crash: it mirrors the curve about 0.5.

        A flipped token leg leaves every row self-consistent, so only a
        calibration statistic can see it. The slope must come back NEGATIVE.
        """
        p, y = synthetic_market(seed=13)
        slope, _ = cox_slope_intercept(p, 1.0 - y)
        assert slope < 0, "a mirrored market must not report a positive slope"

    def test_brier_ranks_the_tilted_market_worse(self):
        """Sanity on the primary metric, not just the calibration diagnostics."""
        p_ok, y_ok = synthetic_market(seed=21)
        p_bad, y_bad = synthetic_market(k=1.4, seed=21)
        assert brier(p_bad, y_bad) > brier(p_ok, y_ok)


class TestScorerCannotBeFooledByDegenerateInput:
    def test_a_coin_flip_market_is_not_credited_with_resolution(self):
        """p == 0.5 everywhere is calibrated but carries no information."""
        rng = np.random.default_rng(2)
        p = np.full(2000, 0.5)
        y = (rng.random(2000) < 0.5).astype(float)
        m = murphy(p, y, MAX_BINS)
        assert m["resolution"] == pytest.approx(0.0, abs=1e-3)
        assert m["reliability"] == pytest.approx(0.0, abs=1e-3)

    def test_a_certain_market_that_is_wrong_is_caught(self):
        p = np.concatenate([np.full(1000, 0.99), np.full(1000, 0.01)])
        y = np.concatenate([np.zeros(1000), np.ones(1000)])  # always wrong
        assert brier(p, y) > 0.9
        assert ece(p, y, MAX_BINS) > GATE_ECE_MAX
