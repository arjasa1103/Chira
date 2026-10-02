"""Scoring and the nested test (PLAN Phase 5, PREREGISTRATION section 7).

Three things live here, and the separation matters:

- **Scoring**, `score_set`: Brier primary, clipped log loss beside it, ECE and
  the Murphy decomposition. Brier is primary because an unclipped log loss is
  unbounded and one mis-joined label at an extreme price could decide a
  headline (PLAN Phase 5, decided 2026-10-01). Every score goes through
  `holdout.assert_scorable`, so nothing here can touch the sealed season
  before `open_holdout`.
- **The nested test**, `clark_west`: Model A is the market price, Model B is
  the market price plus features. **Clark-West, not Diebold-Mariano**: under
  the null the two nested forecasts are identical in population, the loss
  differential is degenerate, and DM's normal reference does not apply.
- **Both nulls**, because beating only one is a different claim. The identity
  null is the raw market price; the recalibration null is a fitted
  `a + b*logit(p)`. B must LITERALLY nest it -- `B = a + b*logit(p) + f(x)`
  with free `a` and `b` -- or CW does not apply. Winning only against the
  identity null is a recalibration finding about a public tilt, not evidence
  of private information.

**The bootstrap resamples calendar DATES, not rows.** Errors cluster by date
and team, and a season has ~170 game dates, which is few enough that fixed
blocks are lumpy; section 7 therefore specifies a stationary bootstrap, whose
block lengths are geometric. The block count is reported with every result.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .calibration import brier, ece, murphy
from .holdout import assert_scorable

# Section 7 / Phase 2: the log loss is reported clipped, so one impossible
# row cannot dominate a mean that is only a secondary number anyway.
LOG_LOSS_CLIP = (0.01, 0.99)

# Newton's method for the logistic fits below. The same guards the Cox fit
# needed in weeks 4 and 5: start from the intercept-only MLE, damp with a
# backtracking line search, and stop on the GRADIENT rather than on the step,
# because a step criterion reports false non-convergence at the optimum.
NEWTON_MAX_ITER = 100
NEWTON_GRAD_TOL = 1e-8
NEWTON_RIDGE = 1e-8

# Mean block length for the stationary bootstrap, in dates. ~170 game dates
# per season, so a 5-date mean block keeps roughly 34 effective blocks.
MEAN_BLOCK_DATES = 5
BOOTSTRAP_REPS = 2000


def logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return np.log(q / (1 - q))


def inv_logit(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def logistic_mle(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Maximum-likelihood logistic coefficients for a design WITH intercept.

    `x` is (n, k) and must already carry its own intercept column; `y` is 0/1.
    Damped Newton, with the three guards the Cox fit earned the hard way:
    the start is the intercept-only MLE rather than zeros, each step is
    backtracked until the deviance actually falls, and convergence is tested
    on the gradient.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 2 or x.shape[0] != y.shape[0]:
        raise ValueError(f"design {x.shape} does not match {y.shape[0]} labels")
    if y.size == 0:
        raise ValueError("logistic fit of an empty sample is undefined")
    lo, hi = float(np.min(y)), float(np.max(y))
    if lo == hi:
        raise ValueError(f"every outcome is {lo}; the fit is not identified")

    def nll(b: np.ndarray) -> float:
        eta = x @ b
        return float(np.sum(np.logaddexp(0.0, eta) - y * eta))

    beta = np.zeros(x.shape[1])
    # Intercept-only start: assumes column 0 is the intercept, which is what
    # every caller here builds.
    base = float(np.mean(y))
    beta[0] = np.log(base / (1 - base))
    for _ in range(NEWTON_MAX_ITER):
        mu = inv_logit(x @ beta)
        grad = x.T @ (y - mu)
        if float(np.max(np.abs(grad))) < NEWTON_GRAD_TOL:
            break
        w = np.clip(mu * (1 - mu), 1e-12, None)
        hess = x.T @ (x * w[:, None]) + NEWTON_RIDGE * np.eye(x.shape[1])
        step = np.linalg.solve(hess, grad)
        current, t = nll(beta), 1.0
        for _ in range(40):
            if nll(beta + t * step) <= current:
                break
            t *= 0.5
        beta = beta + t * step
    return beta


@dataclass
class Scores:
    n: int
    brier: float
    log_loss: float
    ece: float
    reliability: float
    resolution: float
    uncertainty: float
    # The decomposition is computed on 10 equal-count BINS, so it reproduces
    # the direct Brier only up to the within-bin spread of the forecast.
    # Both are carried, and the gap is printed, because a decomposition
    # quietly disagreeing with the number it decomposes is how a reader is
    # misled about where the error lives.
    brier_from_decomp: float

    @property
    def decomp_gap(self) -> float:
        return self.brier_from_decomp - self.brier

    def lines(self, label: str = "") -> list[str]:
        head = f"{label} " if label else ""
        return [f"{head}n={self.n:,}  Brier {self.brier:.5f}  "
                f"log loss {self.log_loss:.5f}  ECE {self.ece:.5f}",
                f"{' ' * len(head)}Murphy: reliability {self.reliability:.5f} "
                f"- resolution {self.resolution:.5f} "
                f"+ uncertainty {self.uncertainty:.5f} "
                f"= {self.brier_from_decomp:.5f} "
                f"(binning gap {self.decomp_gap:+.5f})"]


def clipped_log_loss(p: np.ndarray, y: np.ndarray) -> float:
    q = np.clip(np.asarray(p, dtype=float), *LOG_LOSS_CLIP)
    y = np.asarray(y, dtype=float)
    return float(np.mean(-(y * np.log(q) + (1 - y) * np.log(1 - q))))


def score_set(p: np.ndarray, y: np.ndarray, *, seasons, game_ids,
              what: str = "scored rows") -> Scores:
    """Every headline number for one forecast, behind the seal's guard."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    assert_scorable(
        [{"season": s, "game_id": g}
         for s, g in zip(seasons, game_ids, strict=True)], what=what)
    m = murphy(p, y)
    return Scores(n=p.size, brier=brier(p, y), log_loss=clipped_log_loss(p, y),
                  ece=ece(p, y), reliability=m["reliability"],
                  resolution=m["resolution"], uncertainty=m["uncertainty"],
                  brier_from_decomp=m["brier_from_decomp"])


# --- the nested test -------------------------------------------------------


@dataclass
class ClarkWest:
    statistic: float
    mean_adjusted: float
    se: float
    p_normal: float
    p_bootstrap: float | None
    n: int
    n_dates: int
    reps: int

    def lines(self, label: str = "") -> list[str]:
        head = f"{label}: " if label else ""
        boot = ("—" if self.p_bootstrap is None
                else f"{self.p_bootstrap:.4f}")
        return [f"{head}CW {self.statistic:+.3f}, one-sided p {self.p_normal:.4f} "
                f"(normal) / {boot} (date bootstrap, {self.reps:,} reps over "
                f"{self.n_dates} dates), n={self.n:,}"]


def cw_terms(y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray) -> np.ndarray:
    """The per-game Clark-West adjusted loss differential.

    `f = (y - p_a)^2 - [(y - p_b)^2 - (p_a - p_b)^2]`. The third term is the
    adjustment: under the null the larger model's extra parameters add pure
    noise, and subtracting its expected contribution is what makes the mean
    centred at zero and the normal reference usable again.
    """
    y = np.asarray(y, dtype=float)
    p_a = np.asarray(p_a, dtype=float)
    p_b = np.asarray(p_b, dtype=float)
    return (y - p_a) ** 2 - ((y - p_b) ** 2 - (p_a - p_b) ** 2)


def stationary_bootstrap_dates(dates: np.ndarray, *, reps: int, rng,
                               mean_block: int = MEAN_BLOCK_DATES
                               ) -> list[np.ndarray]:
    """Row indices for `reps` stationary-bootstrap resamples over DATES.

    Politis-Romano: block lengths are geometric with mean `mean_block`, and
    the date sequence wraps, so every date has the same chance of starting a
    block and the resample is stationary. Rows are then every row on each
    chosen date, which is what keeps same-night games together.
    """
    order = np.unique(dates)
    by_date = {d: np.flatnonzero(dates == d) for d in order}
    n_dates = order.size
    if n_dates == 0:
        raise ValueError("no dates to resample")
    pr = 1.0 / mean_block
    out = []
    for _ in range(reps):
        picked: list[int] = []
        while len(picked) < n_dates:
            start = int(rng.integers(n_dates))
            length = int(rng.geometric(pr))
            for j in range(min(length, n_dates - len(picked))):
                picked.append((start + j) % n_dates)
        out.append(np.concatenate([by_date[order[i]] for i in picked]))
    return out


def clark_west(y: np.ndarray, p_a: np.ndarray, p_b: np.ndarray, *,
               dates: np.ndarray | None = None, reps: int = BOOTSTRAP_REPS,
               seed: int = 0, mean_block: int = MEAN_BLOCK_DATES) -> ClarkWest:
    """Clark-West MSPE-adjusted test that B beats the nested A.

    One-sided: the alternative is that B improves on A. The analytic normal
    p-value is reported alongside the date-block bootstrap, as section 7
    requires, because the two disagreeing is itself information.
    """
    from math import erf, sqrt

    f = cw_terms(y, p_a, p_b)
    n = f.size
    if n < 2:
        raise ValueError("Clark-West needs at least two games")
    mean = float(np.mean(f))
    se = float(np.std(f, ddof=1) / sqrt(n))
    stat = mean / se if se > 0 else 0.0
    p_normal = 0.5 * (1.0 - erf(stat / sqrt(2.0)))

    p_boot, n_dates = None, 0
    if dates is not None:
        rng = np.random.default_rng(seed)
        idx = stationary_bootstrap_dates(np.asarray(dates), reps=reps,
                                         rng=rng, mean_block=mean_block)
        n_dates = int(np.unique(dates).size)
        # Centred at the observed mean: the bootstrap distribution of
        # (mean* - mean) approximates the null, so the ASL is how often a
        # resample falls at or below zero under that recentring.
        draws = np.array([float(np.mean(f[i])) for i in idx])
        p_boot = float(np.mean((draws - mean) >= mean))
    return ClarkWest(statistic=stat, mean_adjusted=mean, se=se,
                     p_normal=p_normal, p_bootstrap=p_boot, n=n,
                     n_dates=n_dates, reps=reps if dates is not None else 0)


def recalibration_null(p_fit: np.ndarray, y_fit: np.ndarray,
                       p_apply: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The fitted `a + b*logit(p)` null, estimated on one set, applied to another.

    Returns (predictions, [a, b]). Section 7: B must literally nest this, so
    the same two columns go into B's design.
    """
    x = np.column_stack([np.ones_like(p_fit, dtype=float), logit(p_fit)])
    coef = logistic_mle(x, y_fit)
    z = np.column_stack([np.ones_like(p_apply, dtype=float), logit(p_apply)])
    return inv_logit(z @ coef), coef


@dataclass
class NestedFit:
    """Model A (market) and Model B (market + features), fitted on dev."""
    coef_b: np.ndarray
    columns: tuple[str, ...]
    coef_recal: np.ndarray
    n_fit: int

    def lines(self) -> list[str]:
        out = [f"Model B fitted on {self.n_fit:,} dev games",
               f"  recalibration null: a={self.coef_recal[0]:+.4f}, "
               f"b={self.coef_recal[1]:+.4f}"]
        for name, c in zip(self.columns, self.coef_b, strict=True):
            out.append(f"  B[{name}] {c:+.4f}")
        return out


def _design_b(p_market: np.ndarray, features: np.ndarray) -> np.ndarray:
    """`[1, logit(p), x...]`, so B literally nests `a + b*logit(p)`."""
    return np.column_stack([np.ones_like(p_market, dtype=float),
                            logit(p_market), np.asarray(features, dtype=float)])


def fit_nested(p_market: np.ndarray, features: np.ndarray, y: np.ndarray, *,
               feature_names: tuple[str, ...]) -> NestedFit:
    """Fit B and the recalibration null on the SAME dev window.

    Section 7: a fixed estimation scheme, one dev window, and a single pass
    over the holdout afterwards. Nothing here looks at the target set.
    """
    x = _design_b(p_market, features)
    coef_b = logistic_mle(x, y)
    _, coef_recal = recalibration_null(p_market, y, p_market)
    return NestedFit(coef_b=coef_b,
                     columns=("intercept", "logit_price", *feature_names),
                     coef_recal=coef_recal, n_fit=int(np.asarray(y).size))


def apply_nested(nf: NestedFit, p_market: np.ndarray, features: np.ndarray
                 ) -> dict[str, np.ndarray]:
    """Model A under both nulls, and Model B, on a target set.

    Returns `identity` (the raw market price), `recalibrated`
    (`a + b*logit(p)` with the dev-fitted coefficients) and `b`.
    """
    p_market = np.asarray(p_market, dtype=float)
    z = np.column_stack([np.ones_like(p_market), logit(p_market)])
    return {"identity": p_market,
            "recalibrated": inv_logit(z @ nf.coef_recal),
            "b": inv_logit(_design_b(p_market, features) @ nf.coef_b)}


# --- risk tiers ------------------------------------------------------------

# Pre-registered buckets on the model's probability. Reported with frequency,
# hit rate, calibration and a game-level bootstrap interval, and the expected
# shrinkage of the top tier is stated up front rather than discovered.
RISK_TIERS: tuple[tuple[float, float], ...] = (
    (0.0, 0.35), (0.35, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 1.0),
)


@dataclass
class Tier:
    lo: float
    hi: float
    n: int
    share: float
    mean_p: float
    hit_rate: float
    ci: tuple[float, float]

    def line(self) -> str:
        return (f"  [{self.lo:.2f}, {self.hi:.2f})  n={self.n:>5} "
                f"({self.share * 100:>5.1f}%)  mean p {self.mean_p:.4f}  "
                f"actual {self.hit_rate:.4f}  "
                f"95% CI [{self.ci[0]:.4f}, {self.ci[1]:.4f}]")


def risk_tiers(p: np.ndarray, y: np.ndarray, *,
               tiers: tuple[tuple[float, float], ...] = RISK_TIERS,
               reps: int = BOOTSTRAP_REPS, seed: int = 0) -> list[Tier]:
    """Frequency, hit rate and a game-level bootstrap interval per bucket."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    rng = np.random.default_rng(seed)
    out = []
    for lo, hi in tiers:
        mask = (p >= lo) & (p < hi) if hi < 1.0 else (p >= lo) & (p <= hi)
        n = int(mask.sum())
        if n == 0:
            out.append(Tier(lo, hi, 0, 0.0, float("nan"), float("nan"),
                            (float("nan"), float("nan"))))
            continue
        ys = y[mask]
        draws = np.array([float(np.mean(rng.choice(ys, size=n, replace=True)))
                          for _ in range(reps)])
        out.append(Tier(lo=lo, hi=hi, n=n, share=n / p.size,
                        mean_p=float(np.mean(p[mask])),
                        hit_rate=float(np.mean(ys)),
                        ci=(float(np.quantile(draws, 0.025)),
                            float(np.quantile(draws, 0.975)))))
    return out
