"""The Cox recalibration fit's numerics, pinned against independent truth.

This file exists because of a week-4 bug. `cox_slope_intercept` used undamped
Newton-Raphson from a fixed (a=0, b=1) start and DIVERGED on ordinary samples
whose outcome carries no signal, then reported the data as "degenerate". The
true slope in that regime is 0 and the fit is easy; the estimator was at fault.

Why it matters enough to get its own file: PREREGISTRATION.md section 7 makes
`a + b*logit(p)` the NULL of the single primary test, and section 4 adopts the
Cox slope as a gate bound. A market with little information is exactly where
both get evaluated, and the fit was broken precisely there.

The expected values below come from scipy's BFGS minimization of the negative
log-likelihood, which is an independent implementation of the same estimand.
"""

from __future__ import annotations

import numpy as np
import pytest

from chira.calibration import cox_slope_intercept


def zero_signal(seed, n=800):
    """Ordinary sample, outcome INDEPENDENT of price. True slope is 0.

    Verified non-degenerate for seed 4: not separable, 729 distinct prices,
    y mean 0.415. Nothing here justifies a failed fit.
    """
    rng = np.random.default_rng(seed)
    p = np.clip(rng.uniform(0.1, 0.9, n) + 0.15, 0.01, 0.99)
    y = (rng.random(n) < 0.4).astype(float)
    return p, y


def calibrated(seed, n=800):
    """Outcome drawn FROM the price. True slope is 1."""
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.05, 0.95, n)
    return p, (rng.random(n) < p).astype(float)


class TestZeroSignalDoesNotDiverge:
    @pytest.mark.parametrize("seed", range(6))
    def test_it_fits_a_near_zero_slope_instead_of_raising(self, seed):
        """All six of these seeds used to raise. That was the bug."""
        slope, _ = cox_slope_intercept(*zero_signal(seed))
        assert abs(slope) < 0.35, "true slope is 0; a large |slope| is a runaway"

    @pytest.mark.parametrize("seed", range(6))
    def test_the_intercept_recovers_the_base_rate(self, seed):
        p, y = zero_signal(seed)
        _, intercept = cox_slope_intercept(p, y)
        # With no signal the fit is intercept-only, so a ~ logit(mean(y)).
        expected = float(np.log(y.mean() / (1 - y.mean())))
        assert intercept == pytest.approx(expected, abs=0.3)

    def test_it_matches_scipy_to_four_decimals(self):
        """Independent ground truth: scipy BFGS on the same negative log-lik."""
        slope, intercept = cox_slope_intercept(*zero_signal(4))
        assert intercept == pytest.approx(-0.400104, abs=1e-4)
        assert slope == pytest.approx(0.051484, abs=1e-4)


class TestTheFixChangedNothingThatAlreadyWorked:
    def test_a_signal_bearing_sample_returns_its_previous_value(self):
        """Guards the numbers already reported in notes/week4-charts.md.

        Before the fix this sample converged and returned 0.9252621658750151;
        scipy's MLE is 0.925262. The fix must not move a fit that was already
        correct, or every published figure shifts under it.
        """
        slope, intercept = cox_slope_intercept(*calibrated(0))
        assert slope == pytest.approx(0.925262, abs=1e-4)
        assert intercept == pytest.approx(-0.018876, abs=1e-4)

    @pytest.mark.parametrize("seed", range(4))
    def test_a_calibrated_market_still_lands_near_identity(self, seed):
        slope, _ = cox_slope_intercept(*calibrated(seed, n=3000))
        assert slope == pytest.approx(1.0, abs=0.2)

    def test_a_tilt_is_still_recovered_with_the_right_sign(self):
        """The fix must not flatten real signal toward the slope-0 start."""
        from scipy.special import expit, logit
        rng = np.random.default_rng(5)
        p_true = rng.uniform(0.05, 0.95, 4000)
        y = (rng.random(4000) < p_true).astype(float)
        over = np.clip(expit(1.3 * logit(p_true)), 1e-4, 1 - 1e-4)
        slope, _ = cox_slope_intercept(over, y)
        assert slope == pytest.approx(1 / 1.3, abs=0.12)
        assert slope < 1.0


class TestGenuineDegeneracyStillRaises:
    """The fix must not turn "cannot be fit" into a fabricated number."""

    def test_constant_price_is_singular_and_raises(self):
        """Previously reported slope 165.04 as if it were a result."""
        with pytest.raises(ValueError):
            cox_slope_intercept(np.full(200, 0.6), (np.arange(200) < 120).astype(float))

    def test_perfectly_separable_data_raises(self):
        """The MLE is infinite here. A finite number would be a lie."""
        p = np.linspace(0.05, 0.95, 400)
        y = (p > 0.5).astype(float)
        with pytest.raises(ValueError, match=r"separable|singular|converge"):
            cox_slope_intercept(p, y)

    def test_all_outcomes_identical_raises_or_returns_flat(self):
        """y all 1: the intercept diverges. Must not silently report a slope."""
        p = np.linspace(0.05, 0.95, 300)
        with pytest.raises(ValueError):
            cox_slope_intercept(p, np.ones(300))

    def test_the_error_does_not_blame_the_data_for_an_estimator_failure(self):
        p = np.linspace(0.05, 0.95, 400)
        y = (p > 0.5).astype(float)
        with pytest.raises(ValueError) as e:
            cox_slope_intercept(p, y)
        assert "not a calibration result" in str(e.value) or "singular" in str(e.value)
