"""The hierarchical logistic win-probability model (PLAN Phase 4).

What it is, and what it deliberately is not:

- **A price-free model.** The market price is banned from it; it exists only
  for the Phase 5 nested test. `model_frame` has no price column and
  `tests/test_model.py` asserts it, the same guarantee `features.py` carries.
- **Team strength is the Elo, not a latent walk.** A4's pre-commit chose a
  deterministic rolling rating computed outside the model (Amendment 5b)
  because a latent walk is ~75k parameters on 5,084 observations, and because
  it is the only form that produces a holdout-season team effect from
  information available before each holdout game. The model takes
  `ratings.MODEL_COVARIATE`, which EXCLUDES the home bonus (5b, third
  reading); home advantage is the model's own.
- **Non-centred**, so the funnel geometry does not eat the sampler.
- **Diagnostics are hard failures** (T5): any divergence, or an R-hat above
  `MAX_RHAT`, raises. A quietly non-converged posterior produces a
  real-looking Brier score, which is worse than a crash.

**Readings recorded where the plan leaves a choice** (all settled before the
first fit; none chosen on a fitted result):

1. **One fit per sport, not one model with a sport fixed effect.** Phase 4
   says sport enters as a fixed effect, which shifts an intercept. Amendment
   5a already gives the NHL a different back-to-back structure from the NBA,
   and the two Elo scales differ by a factor of ~2.3 in mean |rating
   difference| (124.0 against 54.2 on dev), so a shared slope would be
   meaningless. Separate fits subsume a sport fixed effect and are strictly
   more flexible. `SPORTS` lists them; nothing is pooled across sports.
2. **Amendment 5d's median fill is extended to rest and time-zone shift**, not
   just travel. 5d covers a neutral-site game's missing travel. A season
   opener has no previous game at all, so rest, travel and time-zone shift are
   all NULL for 62 of 2,542 dev games (2.4%). The same rule applies -- the
   sport's dev median -- and `FillReport` carries every count into the fit
   report, which is what 5d actually asks for. No new indicator column is
   added: that would be a model term the pre-registration does not list.
3. **Prior win rate is NOT a model covariate.** Phase 3 builds it and Phase 4
   does not list it. The Elo is this project's prior-results feature, in a
   better-conditioned form, and adding a raw win rate beside it would be
   collinear with the thing A4 pre-committed to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .holdout import DEV_SEASON, HoldoutError, assert_dev_only
from .ratings import MODEL_COVARIATE

SPORTS = ("nba", "nhl")

# Amendment 5a: the NBA is symmetric in back-to-backs (18.6/18.0) so one
# coefficient on the difference; the NHL is not (21.1 road against 9.2 home)
# so two global coefficients, because one would absorb part of home advantage.
FEATURE_TERMS: dict[str, tuple[str, ...]] = {
    "nba": ("rest_diff", "b2b_diff", "travel_diff", "tz_diff"),
    "nhl": ("rest_diff", "home_b2b", "away_b2b", "travel_diff", "tz_diff"),
}

# Columns filled with the dev median when NULL (reading 2 above).
FILLED = ("away_rest_days", "home_rest_days", "away_travel_km",
          "home_travel_km", "away_tz_shift", "home_tz_shift")

# T5: hard failures, not warnings.
MAX_RHAT = 1.01
MAX_DIVERGENCES = 0

# Measured 2026-10-01: at 1000/1000 the NBA fit reached R-hat 1.0097 against
# the 1.01 hard failure -- 0.0003 of margin, which another seed would spend.
# At 1500/1500 both sports land at 1.0013 and 1.0006 with min ESS above 1,100.
# The threshold is pre-registered and not negotiable, so the sample count is
# what moves.
WARMUP = 1500
SAMPLES = 1500
CHAINS = 4

# Priors. Set on the STANDARDISED design (see `standardise`), so a Normal(0,1)
# slope means "one dev standard deviation of this feature moves the log odds
# by about 1", which is already generous for a schedule feature.
PRIORS: dict[str, float] = {
    "alpha": 1.5,        # intercept: the home base rate lives here
    "mu_home": 0.5,      # global home advantage, on top of the intercept
    "b_rating": 1.0,     # the Elo covariate
    "b_feature": 0.5,    # rest, back-to-backs, travel, time zone
    "tau_team": 0.5,     # residual team-season strength beyond the Elo
    "tau_home": 0.25,    # per-team-season home advantage
}


@dataclass
class FillReport:
    """How many values Amendment 5d's rule filled, per column."""
    counts: dict[str, int] = field(default_factory=dict)
    medians: dict[str, float] = field(default_factory=dict)
    n_rows: int = 0

    def lines(self) -> list[str]:
        out = [f"missing-value fill (Amendment 5d), {self.n_rows:,} rows:"]
        if not any(self.counts.values()):
            out.append("  nothing filled")
        for col in sorted(self.counts):
            n = self.counts[col]
            if n:
                out.append(f"  {col}: {n} filled with dev median "
                           f"{self.medians[col]:.4g}")
        return out


def _col(rows: list[dict], name: str) -> np.ndarray:
    return np.array([r[name] for r in rows], dtype=object)


def dev_medians(rows: list[dict]) -> dict[str, float]:
    """Per-column medians over the DEV rows, which is what 5d specifies.

    Taken from dev even when the frame being filled is the holdout, so the
    fill value is a frozen number and not a quantity that changes with the
    season being predicted.
    """
    out = {}
    for col in FILLED:
        vals = np.array([r[col] for r in rows
                         if r["season"] == DEV_SEASON and r[col] is not None],
                        dtype=float)
        if vals.size == 0:
            raise ValueError(f"no dev values for {col}: cannot fill from a "
                             f"median that does not exist")
        out[col] = float(np.median(vals))
    return out


def fill_missing(rows: list[dict], medians: dict[str, float]
                 ) -> tuple[list[dict], FillReport]:
    """Apply the median fill and count every substitution."""
    report = FillReport(medians=dict(medians), n_rows=len(rows),
                        counts={c: 0 for c in FILLED})
    out = []
    for src in rows:
        r = dict(src)
        for col in FILLED:
            if r[col] is None:
                r[col] = medians[col]
                report.counts[col] += 1
        out.append(r)
    return out, report


def derive_terms(rows: list[dict]) -> list[dict]:
    """The model's feature columns, from the feature store's raw ones."""
    out = []
    for src in rows:
        r = dict(src)
        r["rest_diff"] = float(r["home_rest_days"]) - float(r["away_rest_days"])
        r["home_b2b"] = 1.0 if r["home_b2b"] else 0.0
        r["away_b2b"] = 1.0 if r["away_b2b"] else 0.0
        r["b2b_diff"] = r["home_b2b"] - r["away_b2b"]
        r["travel_diff"] = float(r["home_travel_km"]) - float(r["away_travel_km"])
        r["tz_diff"] = float(r["home_tz_shift"]) - float(r["away_tz_shift"])
        out.append(r)
    return out


@dataclass
class Design:
    """Everything a fit needs, and nothing it must not see."""
    sport: str
    seasons: tuple[str, ...]
    game_ids: list[str]
    y: np.ndarray                 # home win, 0/1
    rating: np.ndarray            # standardised MODEL_COVARIATE
    features: np.ndarray          # (n, k) standardised
    feature_names: tuple[str, ...]
    home_idx: np.ndarray          # team-season index
    away_idx: np.ndarray
    team_seasons: list[str]
    not_neutral: np.ndarray       # 1.0 when the home bonus applies
    scaler: dict[str, tuple[float, float]]
    fill: FillReport

    @property
    def n(self) -> int:
        return len(self.y)

    @property
    def n_team_seasons(self) -> int:
        return len(self.team_seasons)


def standardise(x: np.ndarray, stats: tuple[float, float] | None = None
                ) -> tuple[np.ndarray, tuple[float, float]]:
    """Centre and scale. `stats` reuses a frozen dev mean and sd.

    A constant column gets sd 1 rather than 0, so a feature that happens not
    to vary in one season does not produce NaNs; its coefficient is then
    unidentified and the prior carries it, which is the honest outcome.
    """
    if stats is None:
        mu = float(np.mean(x))
        sd = float(np.std(x))
        stats = (mu, sd if sd > 0 else 1.0)
    mu, sd = stats
    return (x - mu) / sd, stats


def build_design(rows: list[dict], *, sport: str,
                 scaler: dict[str, tuple[float, float]] | None = None,
                 medians: dict[str, float] | None = None,
                 dev_rows: list[dict] | None = None) -> Design:
    """One sport's design matrix.

    `scaler` and `medians` are passed in when building a frame that must use
    DEV statistics -- the holdout frame, or a rolling-origin fold -- so no
    quantity is ever computed from the rows being predicted.
    """
    rows = [r for r in rows if r["sport"] == sport]
    if not rows:
        raise ValueError(f"no {sport} rows")
    source = dev_rows if dev_rows is not None else rows
    medians = medians if medians is not None else dev_medians(
        [r for r in source if r["sport"] == sport])
    rows, fill = fill_missing(rows, medians)
    rows = derive_terms(rows)
    rows.sort(key=lambda r: (r["season"], r["game_id"]))

    names = FEATURE_TERMS[sport]
    scaler = dict(scaler or {})
    rating_raw = np.array([float(r[MODEL_COVARIATE]) for r in rows])
    rating, scaler[MODEL_COVARIATE] = standardise(
        rating_raw, scaler.get(MODEL_COVARIATE))
    cols = []
    for name in names:
        col, scaler[name] = standardise(
            np.array([float(r[name]) for r in rows]), scaler.get(name))
        cols.append(col)

    keys = sorted({f"{r['season']}:{t}" for r in rows
                   for t in (r["home"], r["away"])})
    index = {k: i for i, k in enumerate(keys)}
    return Design(
        sport=sport,
        seasons=tuple(sorted({r["season"] for r in rows})),
        game_ids=[r["game_id"] for r in rows],
        y=np.array([float(r["y"]) for r in rows]),
        rating=rating,
        features=np.column_stack(cols) if cols else np.zeros((len(rows), 0)),
        feature_names=names,
        home_idx=np.array([index[f"{r['season']}:{r['home']}"] for r in rows]),
        away_idx=np.array([index[f"{r['season']}:{r['away']}"] for r in rows]),
        team_seasons=keys,
        not_neutral=np.array([0.0 if r["neutral_site"] else 1.0 for r in rows]),
        scaler=scaler,
        fill=fill,
    )


def assert_fit_is_dev_only(rows: list[dict]) -> None:
    """The fit's own guard. Called by `fit`, never optional."""
    assert_dev_only(rows, what="model rows")


# --- the model -------------------------------------------------------------
#
# logit P(home wins) =
#       alpha                                   intercept; the base rate
#     + mu_home * not_neutral                   global home advantage
#     + b_rating * z(rating_diff_strength)      the frozen Elo, H excluded
#     + sum_j b_j * z(feature_j)                rest, b2b, travel, time zone
#     + tau_team * (e_home - e_away)            residual team-season strength
#     + tau_home * h[home] * not_neutral        per-team-season home advantage
#
# `mu_home` is weakly identified ON PURPOSE and that was pre-stated: with
# every row oriented home-vs-away it is collinear with `alpha` except on the
# 11 dev neutral-site games, so it is reported as shrunk toward its prior and
# never as an estimate (PREREGISTRATION 5b readings, point 3).


def configure(chains: int = CHAINS) -> None:
    """Ask numpyro for `chains` host devices. Call BEFORE touching jax.

    numpyro reads the device count once, at jax initialisation, so this only
    has an effect from the top of a script. `fit` calls it too, late, where it
    merely warns and falls back to sequential chains.
    """
    import numpyro
    numpyro.set_host_device_count(chains)


def numpyro_model(design: Design, *, priors: dict[str, float] | None = None,
                  y=None):
    """The model, non-centred. Imported lazily by `fit`."""
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist

    p = {**PRIORS, **(priors or {})}
    n_ts = design.n_team_seasons

    alpha = numpyro.sample("alpha", dist.Normal(0.0, p["alpha"]))
    mu_home = numpyro.sample("mu_home", dist.Normal(0.0, p["mu_home"]))
    b_rating = numpyro.sample("b_rating", dist.Normal(0.0, p["b_rating"]))

    k = design.features.shape[1]
    b_feat = numpyro.sample(
        "b_feature", dist.Normal(0.0, p["b_feature"]).expand([k]).to_event(1))

    tau_team = numpyro.sample("tau_team", dist.HalfNormal(p["tau_team"]))
    tau_home = numpyro.sample("tau_home", dist.HalfNormal(p["tau_home"]))
    # Non-centred: the funnel lives in the product, not in the prior.
    e_team = numpyro.sample(
        "e_team", dist.Normal(0.0, 1.0).expand([n_ts]).to_event(1))
    e_home = numpyro.sample(
        "e_home", dist.Normal(0.0, 1.0).expand([n_ts]).to_event(1))

    strength = tau_team * (e_team[design.home_idx] - e_team[design.away_idx])
    home_adv = (mu_home + tau_home * e_home[design.home_idx]) \
        * design.not_neutral
    logits = (alpha + b_rating * design.rating
              + jnp.dot(design.features, b_feat) + strength + home_adv)
    numpyro.deterministic("logits", logits)
    numpyro.sample("obs", dist.Bernoulli(logits=logits), obs=y)


@dataclass
class Diagnostics:
    divergences: int
    max_rhat: float
    worst_param: str
    min_ess: float
    n_eff_param: str

    def lines(self) -> list[str]:
        return [f"divergences: {self.divergences}",
                f"max R-hat: {self.max_rhat:.4f} ({self.worst_param})",
                f"min ESS: {self.min_ess:.0f} ({self.n_eff_param})"]


MIN_CHAINS = 2


def diagnostics(mcmc) -> Diagnostics:
    """R-hat, ESS and the divergence count, over every sampled site.

    **Refuses a single-chain run.** R-hat is a between-chain statistic, so one
    chain cannot produce it -- and a NaN would sail straight through
    `assert_diagnostics`, turning a pre-registered hard gate into a free pass.
    A run that cannot be checked is not a run that passed.
    """
    import numpyro.diagnostics as nd

    samples = mcmc.get_samples(group_by_chain=True)
    n_chains = next(iter(samples.values())).shape[0] if samples else 0
    if n_chains < MIN_CHAINS:
        raise DiagnosticsError(
            f"{n_chains} chain(s): R-hat needs at least {MIN_CHAINS}, and "
            f"T5 makes it a hard gate. A single-chain fit cannot be checked, "
            f"so it cannot pass.")
    worst, max_rhat = "", 0.0
    least, min_ess = "", float("inf")
    for name, draws in samples.items():
        if name == "logits":
            continue
        arr = np.asarray(draws)
        # A NaN R-hat is "could not be checked", and NaN > MAX_RHAT is False,
        # so it would pass the gate silently. Count it as infinitely bad.
        rhat = np.nan_to_num(np.asarray(nd.gelman_rubin(arr), dtype=float),
                             nan=np.inf)
        ess = np.nan_to_num(np.asarray(nd.effective_sample_size(arr),
                                       dtype=float), nan=0.0)
        if float(np.max(rhat)) > max_rhat:
            max_rhat, worst = float(np.max(rhat)), name
        if float(np.min(ess)) < min_ess:
            min_ess, least = float(np.min(ess)), name
    extra = mcmc.get_extra_fields()
    div = int(np.sum(np.asarray(extra["diverging"]))) \
        if "diverging" in extra else 0
    return Diagnostics(div, max_rhat, worst, min_ess, least)


class DiagnosticsError(RuntimeError):
    """T5: a non-converged posterior is a failure, not a warning."""


def assert_diagnostics(d: Diagnostics) -> None:
    """Raise on any divergence or an R-hat above MAX_RHAT.

    PREREGISTRATION section 5: *"MCMC diagnostics are hard failures: any
    divergence or R-hat > 1.01 raises. A quietly non-converged posterior
    produces a real-looking Brier score, which is worse than a crash."*
    """
    problems = []
    if d.divergences > MAX_DIVERGENCES:
        problems.append(f"{d.divergences} divergent transition(s)")
    if d.max_rhat > MAX_RHAT:
        problems.append(f"R-hat {d.max_rhat:.4f} > {MAX_RHAT} "
                        f"on {d.worst_param}")
    if problems:
        raise DiagnosticsError(
            "the posterior did not converge: " + "; ".join(problems)
            + ". This is a hard failure (T5); a real-looking Brier score from "
              "a non-converged chain is worse than a crash.")


@dataclass
class Fit:
    sport: str
    design: Design
    mcmc: object
    diag: Diagnostics
    priors: dict[str, float]

    def p_home(self) -> np.ndarray:
        """Posterior-mean home win probability on the fitted rows."""
        logits = np.asarray(self.mcmc.get_samples()["logits"])
        return np.asarray(1.0 / (1.0 + np.exp(-logits))).mean(axis=0)


def fit(rows: list[dict], *, sport: str, seed: int = 0,
        warmup: int = WARMUP, samples: int = SAMPLES, chains: int = CHAINS,
        priors: dict[str, float] | None = None,
        design: Design | None = None) -> Fit:
    """Fit on DEV rows. Refuses anything else.

    `assert_dev_only` runs before a single sample is drawn: the realistic leak
    is a frame assembled without a season filter, not a stray call.
    """
    import jax
    import numpyro
    from numpyro.infer import MCMC, NUTS

    assert_fit_is_dev_only(rows)
    design = design or build_design(rows, sport=sport)
    # The DESIGN is what gets sampled, so the design is what is checked. The
    # first version checked only `rows`, and a prebuilt design from 2025-26
    # passed in beside harmless dev rows was fitted with every guard green.
    stray = [s for s in design.seasons if s != DEV_SEASON]
    if stray:
        raise HoldoutError(
            f"the design to be fitted carries season(s) {stray}, not only "
            f"{DEV_SEASON}. fit() samples the design, whatever rows come with "
            f"it, so the design is what must be dev-only.")
    # Best effort: numpyro only honours this before jax initialises, so a
    # caller that has already touched jax gets sequential chains and a
    # warning. Correctness is unaffected -- it is a wall-clock matter -- and a
    # runner that wants parallel chains calls `configure` first.
    numpyro.set_host_device_count(chains)
    kernel = NUTS(numpyro_model, target_accept_prob=0.9)
    mcmc = MCMC(kernel, num_warmup=warmup, num_samples=samples,
                num_chains=chains, progress_bar=False)
    mcmc.run(jax.random.PRNGKey(seed), design, priors=priors,
             y=design.y, extra_fields=("diverging",))
    d = diagnostics(mcmc)
    assert_diagnostics(d)
    return Fit(sport=sport, design=design, mcmc=mcmc, diag=d,
               priors={**PRIORS, **(priors or {})})
