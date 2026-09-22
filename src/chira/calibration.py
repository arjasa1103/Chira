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
NR_MIN_STEP_SCALE = 1e-6
NR_GRAD_TOL = 1e-6
# Identifiability, NOT a gradient. Same magnitude, different unit: this one is
# the spread of logit(p) across the sample, and reusing the gradient tolerance
# for it meant one edit to either meaning silently moved the other.
NR_PRICE_RANGE_TOL = 1e-6

# Above this share of unfittable bootstrap replicates, a null's slope and
# intercept bands are conditioned on convergence and must not be quoted.
MAX_COX_FAILURE_RATE = 0.01


def _nll(a: float, b: float, x: np.ndarray, y: np.ndarray) -> float:
    """Negative log-likelihood. logaddexp keeps it finite at large |eta|."""
    eta = a + b * x
    return float(np.sum(np.logaddexp(0.0, eta) - y * eta))


def cox_slope_intercept(p: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Logistic recalibration: y ~ a + b*logit(p). Perfect => b=1, a=0.

    Raises on non-convergence. Silently returning the last iterate let a
    degenerate sample report slope 165.04 as if it were a calibration result.
    scipy has no logistic fit (that lives in sklearn/statsmodels, neither a
    dependency), so the Newton-Raphson loop stays; only expit/logit come from
    scipy, and expit is overflow-safe where 1/(1+exp(-eta)) is not.

    **Two numerical fixes, week 4.** Undamped Newton from a fixed (a=0, b=1)
    start diverged on ORDINARY samples whose outcome carries no signal, which is
    the true-slope-zero case and the easiest fit there is. Measured on six of
    six seeds with y drawn independently of p (n=800, not separable, 729 distinct
    prices): the start's nll is 868.6 against the MLE's 542.2, the first full
    step overshoots so nll RISES to 1279, the fitted probabilities then saturate,
    the weights pin to NR_WEIGHT_FLOOR, and the iterate runs away to |b| ~ 1e8
    and oscillates until the loop gives up. It then blamed the data as
    "degenerate", which was wrong: scipy puts that sample's MLE at a mundane
    intercept -0.4001, slope +0.0515.

    That regime is not hypothetical. PREREGISTRATION.md section 7 makes
    `a + b*logit(p)` the NULL of the single primary test, and section 4 adopts
    the Cox slope as a gate bound; a market carrying little information is
    exactly where both are evaluated, and NHL 2025-26 already measures a Murphy
    resolution of 0.0055.

    1. **Start at the intercept-only MLE (slope 0), not the identity (slope 1).**
       The no-information fit is the right place to begin a search for signal.
    2. **Backtrack the Newton step while it makes the nll worse.** Newton's
       quadratic convergence is only local; damping makes it global, and either
       fix alone recovers the exact MLE (4 and 8 iterations respectively).

    3. **Convergence is judged on the GRADIENT, week 5.** The first version
       tested the undamped Newton step against 1e-10, which mistook a converged
       fit for a failure. Measured on an NHL bootstrap replicate at n=225: the
       iterate sat exactly on the MLE (slope +2.11450 against scipy's +2.114498,
       gradient 1.1e-9, nll unchanged to 6 decimals), but at the optimum
       floating-point noise makes a full step look like it *worsens* the nll, so
       the line search shrank `t` to 1e-6 and the parameters stopped moving with
       the step stuck at 1.367e-10 — just above the tolerance. It then raised
       "did not converge" on a correct answer, and because `simulate_null` had no
       failure handling, that single replicate in 1,500 killed a whole
       derivation. The gradient is the actual optimality condition, so it is what
       is tested; it is checked BEFORE stepping, which also means a stalled line
       search at a genuine optimum exits cleanly. Genuine separation still fails:
       there the gradient stays large while the iterate runs away.
    """
    _check_nonempty(p, y)
    x = logit(np.clip(p, LOGIT_CLAMP, 1 - LOGIT_CLAMP))
    # Identifiability, checked explicitly BEFORE any convergence test. The
    # gradient criterion below is only meaningful once a slope is identified at
    # all: at the intercept-only start the gradient is already ~0 whenever the
    # design cannot support a slope, so testing it first would report
    # "converged" and hand back slope 0.0 as though it were a measurement.
    # Both cases used to surface as a singular solve, which was luck, not logic.
    if float(np.ptp(x)) < NR_PRICE_RANGE_TOL:
        raise ValueError(
            "cox fit is not identified: every price is the same, so no slope "
            "exists to estimate (a constant-price sample once reported 165.04)")
    if float(np.min(y)) == float(np.max(y)):
        raise ValueError(
            f"cox fit is not identified: every outcome is {float(np.min(y))}, so "
            f"the intercept's MLE is at infinity and no finite fit exists")
    X = np.column_stack([np.ones_like(x), x])
    ybar = float(np.clip(np.mean(y), LOGIT_CLAMP, 1 - LOGIT_CLAMP))
    a, b, converged = float(logit(ybar)), 0.0, False
    for _ in range(NR_MAX_ITER):
        mu = expit(a + b * x)
        grad = X.T @ (y - mu)
        # The optimality condition itself. Each element is a sum of n terms each
        # bounded by 1, so 1e-6 absolute is a strict test at every n here.
        if np.max(np.abs(grad)) < NR_GRAD_TOL:
            converged = True
            break
        w = np.clip(mu * (1 - mu), NR_WEIGHT_FLOOR, None)
        try:
            step = np.linalg.solve(X.T @ (X * w[:, None]), grad)
        except np.linalg.LinAlgError as e:
            raise ValueError(f"cox fit is singular (degenerate sample): {e}") from e
        base = _nll(a, b, x, y)
        t = 1.0
        while t > NR_MIN_STEP_SCALE and _nll(a + t * step[0], b + t * step[1], x, y) > base:
            t /= 2
        a, b = a + t * step[0], b + t * step[1]
        if np.max(np.abs(step)) < NR_TOL:
            converged = True
            break
    if not converged:
        raise ValueError(
            f"cox fit did not converge in {NR_MAX_ITER} damped iterations "
            f"(last slope={b:.4g}). The sample may be separable, or the "
            f"estimator may have failed; either way this is not a calibration "
            f"result and must not be reported as one"
        )
    return float(b), float(a)


def brier(p: np.ndarray, y: np.ndarray) -> float:
    _check_nonempty(p, y)
    return float(np.mean((p - y) ** 2))


# PREREGISTRATION.md section 8: minimum 150 games per probability bin, merging
# bins upward when short. Ten equal-count bins at ~85 games/bin gives SE ~0.054,
# so the tail bins where the literature reports bias would hold a handful of
# games each and the curve would be reporting noise as shape.
MIN_BIN_GAMES = 150
MAX_BINS = 10


def n_bins_for(n: int, min_bin_n: int = MIN_BIN_GAMES, max_bins: int = MAX_BINS) -> int:
    """Bin count honouring the pre-registered 150-game floor. At least 1.

    This is the "merge upward when short" rule applied before binning rather
    than after: choosing the count up front is the same partition you would
    reach by merging adjacent short bins, without the path dependence of
    which neighbour you merge into.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    return max(1, min(max_bins, n // min_bin_n))


def quantile_bin_edges(p: np.ndarray, n_bins: int) -> np.ndarray:
    """Interior price cut points for ~equal-count bins, duplicates removed.

    The chart needs bins defined by PRICE, not by index range, because the
    bootstrap resamples games and index ranges would redefine the bins on every
    replicate (the band would then mix sampling noise with bin drift).

    Equal-count is APPROXIMATE here, and deliberately so: real moneylines pile
    up on round values (0.50 especially, and 2,047 of 4,661 census closes are
    carried forward), so a tied block cannot be split across an edge without
    making membership depend on row order. Duplicate edges are collapsed, ties
    land wholly in one bin, and the realized per-bin n is reported rather than
    assumed equal. `equal_count_bins` keeps the index-range definition, because
    the section-4 noise floor was simulated against it.
    """
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    qs = np.linspace(0, 1, n_bins + 1)[1:-1]
    return np.unique(np.quantile(p, qs)) if len(qs) else np.array([])


def binned_curve(p: np.ndarray, y: np.ndarray, edges: np.ndarray) -> dict:
    """Reliability curve over fixed price edges. Empty bins are dropped."""
    _check_nonempty(p, y)
    idx = np.searchsorted(edges, p, side="right")
    mp, obs, ns, lo, hi = [], [], [], [], []
    for b in range(len(edges) + 1):
        m = idx == b
        if not m.any():
            continue
        mp.append(float(p[m].mean()))
        obs.append(float(y[m].mean()))
        ns.append(int(m.sum()))
        lo.append(float(p[m].min()))
        hi.append(float(p[m].max()))
    return {"mean_p": np.array(mp), "obs_rate": np.array(obs), "n": np.array(ns),
            "p_lo": np.array(lo), "p_hi": np.array(hi)}


def bootstrap_curve(p: np.ndarray, y: np.ndarray, edges: np.ndarray, *,
                    reps: int = 2000, seed: int = 0, alpha: float = 0.05) -> dict:
    """Percentile bands for the reliability curve, resampling GAMES.

    PREREGISTRATION.md section 8: resample games, never rows. Here one game is
    one row, so the two coincide; the distinction becomes load-bearing the
    moment a caller bootstraps several time-to-close looks at once, which is
    why `bootstrap_looks` exists and shares this function's index draws.
    """
    _check_nonempty(p, y)
    rng = np.random.default_rng(seed)
    n_bins = len(edges) + 1
    # NaN-filled so a bin a replicate never populates does not silently become
    # a zero observed rate, which would drag the band toward 0.
    draws = np.full((reps, n_bins), np.nan)
    for i in range(reps):
        take = rng.integers(0, len(p), len(p))
        ps, ys = p[take], y[take]
        idx = np.searchsorted(edges, ps, side="right")
        for b in range(n_bins):
            m = idx == b
            if m.any():
                draws[i, b] = ys[m].mean()
    keep = ~np.all(np.isnan(draws), axis=0)
    with np.errstate(invalid="ignore"):
        lo = np.nanpercentile(draws[:, keep], 100 * alpha / 2, axis=0)
        hi = np.nanpercentile(draws[:, keep], 100 * (1 - alpha / 2), axis=0)
    return {"lo": lo, "hi": hi, "reps": reps}


def bootstrap_scalars(p: np.ndarray, y: np.ndarray, *, reps: int = 2000,
                      seed: int = 0, alpha: float = 0.05, n_bins: int = MAX_BINS) -> dict:
    """Game-level bootstrap CIs for ECE, Brier and the Cox slope/intercept.

    The Cox CI is the form PREREGISTRATION.md section 4 states as an
    EQUIVALENCE test: the interval must lie entirely inside the adopted band,
    so an imprecise estimate fails rather than passing for being vague.

    A replicate whose Cox fit is degenerate is counted, not silently dropped:
    a band computed from the subset of replicates that happened to converge is
    a band conditioned on convergence.
    """
    _check_nonempty(p, y)
    rng = np.random.default_rng(seed)
    out = {"ece": [], "brier": [], "slope": [], "intercept": []}
    failed = 0
    for _ in range(reps):
        take = rng.integers(0, len(p), len(p))
        ps, ys = p[take], y[take]
        out["ece"].append(ece(ps, ys, n_bins))
        out["brier"].append(brier(ps, ys))
        try:
            b, a = cox_slope_intercept(ps, ys)
        except ValueError:
            failed += 1
            continue
        out["slope"].append(b)
        out["intercept"].append(a)
    bands = {k: {"lo": float(np.percentile(v, 100 * alpha / 2)),
                 "hi": float(np.percentile(v, 100 * (1 - alpha / 2))),
                 "p50": float(np.percentile(v, 50))}
             for k, v in out.items() if v}
    return {**bands, "reps": reps, "cox_failures": failed}


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

    **A replicate whose Cox fit will not converge is counted, not fatal, and not
    silently dropped.** This used to raise, so one unfittable draw in 1,500 ended
    a whole derivation (measured: NHL pool, n=225, seed 7). But a null computed
    only over the replicates that converged is a null conditioned on
    convergence, which is a quietly wrong reference distribution. So failures
    are counted, the metrics that do not need a fit still use every replicate,
    and a failure rate above MAX_COX_FAILURE_RATE raises rather than returning a
    biased band.
    """
    rng = np.random.default_rng(seed)
    unfitted = ("ece", "max_bin_dev", "brier")
    out = {k: np.empty(reps) for k in unfitted}
    fits = {"slope": [], "intercept": []}
    failed = 0
    for i in range(reps):
        p = rng.choice(price_pool, size=n, replace=True)
        y = (rng.random(n) < p).astype(float)   # perfectly calibrated by construction
        out["ece"][i] = ece(p, y, n_bins)
        out["max_bin_dev"][i] = max_bin_dev(p, y, n_bins)
        out["brier"][i] = brier(p, y)
        try:
            b, a = cox_slope_intercept(p, y)
        except ValueError:
            failed += 1
            continue
        fits["slope"].append(b)
        fits["intercept"].append(a)
    if failed > MAX_COX_FAILURE_RATE * reps:
        raise ValueError(
            f"{failed} of {reps} replicates at n={n} had no computable Cox fit "
            f"({failed / reps:.1%}); the slope and intercept bands would be "
            f"conditioned on convergence, so they are not returned. Investigate "
            f"the estimator or the pool rather than quoting this null"
        )

    def band(v: np.ndarray) -> dict:
        return {"mean": float(v.mean()),
                "p50": float(np.percentile(v, 50)),
                "p95": float(np.percentile(v, 95)),
                "p99": float(np.percentile(v, 99)),
                "lo2.5": float(np.percentile(v, 2.5)),
                "hi97.5": float(np.percentile(v, 97.5))}

    result = {k: band(out[k]) for k in unfitted}
    result.update({k: band(np.asarray(v)) for k, v in fits.items()})
    result["cox_failures"] = failed
    result["reps"] = reps
    return result
