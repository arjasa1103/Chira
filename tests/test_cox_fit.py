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
from scipy.special import expit, logit

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
        rng = np.random.default_rng(5)
        p_true = rng.uniform(0.05, 0.95, 4000)
        y = (rng.random(4000) < p_true).astype(float)
        over = np.clip(expit(1.3 * logit(p_true)), 1e-4, 1 - 1e-4)
        slope, _ = cox_slope_intercept(over, y)
        assert slope == pytest.approx(1 / 1.3, abs=0.12)
        assert slope < 1.0


def concentrated_pool(n=64):
    """NHL-shaped prices: narrow, most mass near 0.5.

    NHL closes span 0.200-0.825 with 82.6% inside [0.35, 0.65], and that shape is
    what makes small-n fits hard: mass near 0.5 carries the most Bernoulli
    variance, so a 225-game cell can land on an awkward likelihood surface.
    """
    return np.concatenate([np.linspace(0.20, 0.35, n // 8),
                           np.linspace(0.35, 0.65, (3 * n) // 4),
                           np.linspace(0.65, 0.825, n // 8)])


def scipy_mle(p, y):
    """Independent ground truth, by a different algorithm (BFGS, not Newton)."""
    from scipy.optimize import minimize
    from scipy.special import logit as _logit
    x = _logit(np.clip(p, 1e-6, 1 - 1e-6))

    def nll(th):
        eta = th[0] + th[1] * x
        return float(np.sum(np.logaddexp(0, eta) - y * eta))

    r = minimize(nll, [0.0, 0.0], method="BFGS")
    return float(r.x[1]), float(r.x[0])


class TestSmallStrataCellsConverge:
    """Week 5. Headline-2 cells are 221-312 games, which is where this broke.

    The damped loop judged convergence on the undamped Newton STEP against
    1e-10. At the optimum, floating-point noise makes a full step look like it
    worsens the log-likelihood, so the line search shrank t to 1e-6, the
    parameters stopped moving, and the step floored at 1.367e-10 -- just above
    the tolerance. The fit then raised "did not converge" while sitting exactly
    on the MLE (slope +2.11450 vs scipy's +2.114498, gradient 1.1e-9).

    Measured rate: 1 replicate in 1,500 at NHL n=225. Enough to kill a whole
    null derivation, because simulate_null had no failure handling.
    """

    @pytest.mark.parametrize("seed", range(40))
    def test_a_cell_sized_concentrated_sample_fits(self, seed):
        rng = np.random.default_rng(seed)
        p = rng.choice(concentrated_pool(), size=225, replace=True)
        y = (rng.random(225) < p).astype(float)
        slope, _ = cox_slope_intercept(p, y)   # must not raise
        assert np.isfinite(slope)

    @pytest.mark.parametrize("seed", range(12))
    def test_it_agrees_with_scipy_at_cell_size(self, seed):
        """Agreement with a different algorithm, not just self-consistency."""
        rng = np.random.default_rng(100 + seed)
        p = rng.choice(concentrated_pool(), size=225, replace=True)
        y = (rng.random(225) < p).astype(float)
        got_slope, got_intercept = cox_slope_intercept(p, y)
        want_slope, want_intercept = scipy_mle(p, y)
        assert got_slope == pytest.approx(want_slope, abs=1e-3)
        assert got_intercept == pytest.approx(want_intercept, abs=1e-3)

    def test_a_steep_but_finite_mle_is_returned_not_refused(self):
        """The failing replicate's MLE was ~2.11: steep, finite, perfectly valid."""
        rng = np.random.default_rng(3)
        p = rng.choice(concentrated_pool(), size=225, replace=True)
        # outcomes generated with a steeper slope than the quoted price implies
        steep = expit(2.2 * logit(np.clip(p, 1e-6, 1 - 1e-6)))
        y = (rng.random(225) < steep).astype(float)
        slope, _ = cox_slope_intercept(p, y)
        assert slope > 1.4, "a steep relationship must come back steep"
        assert slope == pytest.approx(scipy_mle(p, y)[0], abs=1e-3)


class TestNullSimulationHandlesUnfittableReplicates:
    """A null conditioned on convergence is a quietly wrong reference."""

    def test_a_few_failures_are_counted_and_reported(self, monkeypatch):
        import chira.calibration as cal
        real = cal.cox_slope_intercept
        calls = {"n": 0}

        def flaky(p, y):
            calls["n"] += 1
            if calls["n"] % 500 == 0:      # 0.2%: under the threshold
                raise ValueError("synthetic non-convergence")
            return real(p, y)

        monkeypatch.setattr(cal, "cox_slope_intercept", flaky)
        null = cal.simulate_null(np.linspace(0.1, 0.9, 100), n=200, reps=500, seed=1)
        assert null["cox_failures"] == 1
        assert null["reps"] == 500
        assert null["ece"]["p99"] > 0          # unfitted metrics still complete

    def test_a_high_failure_rate_raises_instead_of_returning_a_biased_band(
            self, monkeypatch):
        import chira.calibration as cal

        def always_fails(p, y):
            raise ValueError("synthetic non-convergence")

        monkeypatch.setattr(cal, "cox_slope_intercept", always_fails)
        with pytest.raises(ValueError, match="conditioned on convergence"):
            cal.simulate_null(np.linspace(0.1, 0.9, 100), n=200, reps=100, seed=1)


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
