"""Calibration metrics and the null-distribution simulator.

The simulator exists because thresholds set by intuition fail on correct data.
An integrity gate whose ECE cap sits below the estimator's own sampling noise
will reject a perfectly calibrated market, and a false "the pipeline is broken"
verdict is the worst outcome that gate can produce.
"""

from __future__ import annotations

import numpy as np


def equal_count_bins(p: np.ndarray, y: np.ndarray, n_bins: int = 10):
    """Return (bin_mean_p, bin_obs_rate, bin_n) using equal-count bins."""
    order = np.argsort(p)
    p, y = p[order], y[order]
    edges = np.linspace(0, len(p), n_bins + 1).astype(int)
    mp, obs, ns = [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        mp.append(p[a:b].mean())
        obs.append(y[a:b].mean())
        ns.append(b - a)
    return np.array(mp), np.array(obs), np.array(ns)


def ece(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    """Expected calibration error, n-weighted."""
    mp, obs, ns = equal_count_bins(p, y, n_bins)
    return float(np.sum(ns * np.abs(obs - mp)) / np.sum(ns))


def max_bin_dev(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    mp, obs, _ = equal_count_bins(p, y, n_bins)
    return float(np.max(np.abs(obs - mp)))


def cox_slope_intercept(p: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Logistic recalibration: y ~ a + b*logit(p). Perfect => b=1, a=0."""
    eps = 1e-6
    x = np.log(np.clip(p, eps, 1 - eps) / (1 - np.clip(p, eps, 1 - eps)))
    b, a = 1.0, 0.0
    for _ in range(60):  # Newton-Raphson
        eta = a + b * x
        mu = 1.0 / (1.0 + np.exp(-eta))
        w = np.clip(mu * (1 - mu), 1e-9, None)
        r = y - mu
        X = np.column_stack([np.ones_like(x), x])
        H = X.T @ (X * w[:, None])
        g = X.T @ r
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        a, b = a + step[0], b + step[1]
        if np.max(np.abs(step)) < 1e-10:
            break
    return float(b), float(a)


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def murphy(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> dict:
    """Brier = reliability - resolution + uncertainty."""
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
