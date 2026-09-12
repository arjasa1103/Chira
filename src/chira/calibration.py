"""Calibration metrics and the null-distribution simulator.

The simulator exists because thresholds set by intuition fail on correct data.
An integrity gate whose ECE cap sits below the estimator's own sampling noise
will reject a perfectly calibrated market, and a false "the pipeline is broken"
verdict is the worst outcome that gate can produce.
"""

from __future__ import annotations

import itertools

import numpy as np
from scipy.special import expit, logit


def _check_nonempty(p: np.ndarray, y: np.ndarray) -> None:
    """Empty input must raise, never return nan.

    A nan ECE compared against the gate evaluates False, so an empty or
    fully-filtered stratum would pass the integrity gate silently.
    """
    if len(p) == 0 or len(y) == 0:
        raise ValueError("empty sample: refusing to return a nan metric")
    if len(p) != len(y):
        raise ValueError(f"length mismatch: {len(p)} prices vs {len(y)} outcomes")


def equal_count_bins(p: np.ndarray, y: np.ndarray, n_bins: int = 10):
    """Return (bin_mean_p, bin_obs_rate, bin_n) using equal-count bins.

    Sort is STABLE: real moneylines pile up on round values like 0.50, and an
    unstable sort makes tie assignment across a bin boundary platform-dependent.
    A pre-registered study has to be bit-reproducible.
    """
    _check_nonempty(p, y)
    order = np.argsort(p, kind="stable")
    p, y = p[order], y[order]
    edges = np.linspace(0, len(p), n_bins + 1).astype(int)
    mp, obs, ns = [], [], []
    for a, b in itertools.pairwise(edges):
        if b <= a:
            continue
        mp.append(p[a:b].mean())
        obs.append(y[a:b].mean())
        ns.append(b - a)
    return np.array(mp), np.array(obs), np.array(ns)


def ece(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    """Expected calibration error, n-weighted."""
    _check_nonempty(p, y)
    mp, obs, ns = equal_count_bins(p, y, n_bins)
    return float(np.sum(ns * np.abs(obs - mp)) / np.sum(ns))


def max_bin_dev(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    _check_nonempty(p, y)
    mp, obs, _ = equal_count_bins(p, y, n_bins)
    return float(np.max(np.abs(obs - mp)))


LOGIT_CLAMP = 1e-6
NR_MAX_ITER = 60
NR_TOL = 1e-10
NR_WEIGHT_FLOOR = 1e-9


def cox_slope_intercept(p: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Logistic recalibration: y ~ a + b*logit(p). Perfect => b=1, a=0.

    Raises on non-convergence. Silently returning the last iterate let a
    degenerate sample report slope 165.04 as if it were a calibration result.
    scipy has no logistic fit (that lives in sklearn/statsmodels, neither a
    dependency), so the Newton-Raphson loop stays; only expit/logit come from
    scipy, and expit is overflow-safe where 1/(1+exp(-eta)) is not.
    """
    _check_nonempty(p, y)
    x = logit(np.clip(p, LOGIT_CLAMP, 1 - LOGIT_CLAMP))
    X = np.column_stack([np.ones_like(x), x])
    b, a, converged = 1.0, 0.0, False
    for _ in range(NR_MAX_ITER):
        mu = expit(a + b * x)
        w = np.clip(mu * (1 - mu), NR_WEIGHT_FLOOR, None)
        try:
            step = np.linalg.solve(X.T @ (X * w[:, None]), X.T @ (y - mu))
        except np.linalg.LinAlgError as e:
            raise ValueError(f"cox fit is singular (degenerate sample): {e}") from e
        a, b = a + step[0], b + step[1]
        if np.max(np.abs(step)) < NR_TOL:
            converged = True
            break
    if not converged:
        raise ValueError(
            f"cox fit did not converge in {NR_MAX_ITER} iterations "
            f"(last slope={b:.4g}); sample is degenerate, not calibrated"
        )
    return float(b), float(a)


def brier(p: np.ndarray, y: np.ndarray) -> float:
    _check_nonempty(p, y)
    return float(np.mean((p - y) ** 2))


def murphy(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> dict:
    """Brier = reliability - resolution + uncertainty."""
    _check_nonempty(p, y)
    mp, obs, ns = equal_count_bins(p, y, n_bins)
    n = np.sum(ns)
    ybar = float(np.mean(y))
    rel = float(np.sum(ns * (mp - obs) ** 2) / n)
    res = float(np.sum(ns * (obs - ybar) ** 2) / n)
    unc = ybar * (1 - ybar)
    return {"reliability": rel, "resolution": res, "uncertainty": unc,
            "brier_from_decomp": rel - res + unc, "brier_direct": brier(p, y)}


def simulate_null(price_pool: np.ndarray, n: int, reps: int = 4000,
                  n_bins: int = 10, seed: int = 0) -> dict:
    """Null distribution of the metrics under a PERFECTLY calibrated market.

    Prices are bootstrapped from the empirical pool so the simulated market has
    the real shape (NBA moneylines concentrate roughly in 0.2-0.9, which changes
    the bin occupancy and therefore the noise floor).
    """
    rng = np.random.default_rng(seed)
    out = {k: np.empty(reps) for k in ("ece", "max_bin_dev", "slope", "intercept", "brier")}
    for i in range(reps):
        p = rng.choice(price_pool, size=n, replace=True)
        y = (rng.random(n) < p).astype(float)   # perfectly calibrated by construction
        out["ece"][i] = ece(p, y, n_bins)
        out["max_bin_dev"][i] = max_bin_dev(p, y, n_bins)
        b, a = cox_slope_intercept(p, y)
        out["slope"][i], out["intercept"][i] = b, a
        out["brier"][i] = brier(p, y)
    return {k: {"mean": float(v.mean()),
                "p50": float(np.percentile(v, 50)),
                "p95": float(np.percentile(v, 95)),
                "p99": float(np.percentile(v, 99)),
                "lo2.5": float(np.percentile(v, 2.5)),
                "hi97.5": float(np.percentile(v, 97.5))}
            for k, v in out.items()}
