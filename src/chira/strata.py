"""Headline 2: the market's own calibration, by liquidity and season phase.

The pre-registered design is PREREGISTRATION.md section 8 plus Amendments 3a,
3b and 4. Each rule below exists because the obvious version of it was measured
and found wrong, so the reasons travel with the code:

- **A 2x2: liquidity x season phase, cut WITHIN each sport-season.** Both axes
  are equal-count median splits, so each sport-season yields four cells of
  221-312 games.
- **Liquidity is cut inside each PHASE, not inside the season** (Amendment 3a).
  Cutting within the season left 66-72% of low-liquidity games early, because
  volume climbs steeply through a season (Spearman +0.36 to +0.53). The two axes
  of the 2x2 were then close to the same cut, and the primary test is a
  difference BETWEEN strata, so the confound landed directly on the headline.
  Within-phase cutting restores 0.503-0.534.
- **The primary directional test is NBA-only** (Amendment 3b). NHL is reported
  in full as the contrast case: a market can be perfectly calibrated and carry
  almost no information (Murphy resolution 0.0057 for NHL 2025-26 against
  0.0520 for NBA), and such a market cannot be shown to be miscalibrated in an
  interesting way at any n.
- **Games with no volume are excluded from the liquidity axis and never
  proxied** (Amendment 4). 318 games in a 2026-03 block have no per-market
  volume anywhere in Gamma. Amendment 3c had adopted event-level volume as a
  proxy; week 5 measured it at $350-$11,169 against season medians of $604k and
  $2.03M, so it would have labelled late-season games low-liquidity on an
  artifact. They stay in the phase axis and in every unstratified number.
- **Per-cell metrics are read against the null at THEIR OWN n**, never the
  pooled cap (section 4). This matters more than it sounds: at NHL n=225 a
  perfectly calibrated market has a null ECE p99 of 0.1288, so per-cell
  calibration is close to unfalsifiable and the honest report says so.
"""

from __future__ import annotations

import numpy as np

from .calibration import (
    MAX_BINS,
    MAX_COX_FAILURE_RATE,
    brier,
    cox_slope_intercept,
    ece,
    murphy,
    n_bins_for,
)
from .constants import CENSUS_NULL_ECE_P99_BY_N, CENSUS_NULL_SLOPE_CI_BY_N

# Matches extract.py's clamp so logit() never sees an exact 0 or 1.
LOGIT_EPS = 1e-6

PHASES = ("early", "late")
LEVELS = ("low", "high")
ABSENT = ""          # liquidity label for a game with no volume
PRIMARY_SPORT = "nba"


def _median_split(values: np.ndarray, low_label: str, high_label: str) -> np.ndarray:
    """Equal-count split at the median. Ties go to the LOW/EARLY side.

    Deterministic tie handling is not cosmetic here: week-of-season is a small
    integer, so a whole week of games sits on the median and a coin-flip rule
    would move ~50 games between cells between runs.
    """
    cut = float(np.median(values))
    return np.where(values <= cut, low_label, high_label)


def assign_strata(f: dict) -> dict:
    """Add `phase`, `liquidity` and `cell` to a frame. Returns the cut points.

    Cuts are computed inside each (sport, season): a stratum means "low volume
    for this sport, this season, at this point in the season", which is the
    quantity section 8 intended.
    """
    n = len(f["game_id"])
    phase = np.full(n, "", dtype=object)
    liquidity = np.full(n, ABSENT, dtype=object)
    cuts = {}
    pairs = sorted({(s, se) for s, se in zip(f["sport"], f["season"], strict=True)})
    for sport, season in pairs:
        grp = (f["sport"] == sport) & (f["season"] == season)
        weeks = f["week_of_season"][grp]
        phase[grp] = _median_split(weeks, "early", "late")
        record = {"week_median": float(np.median(weeks)), "n": int(grp.sum())}
        for ph in PHASES:
            m = grp & (phase == ph)
            vol = f["volume"][m]
            has = ~np.isnan(vol)
            if has.sum() == 0:
                record[f"volume_median_{ph}"] = None
                continue
            cut = float(np.median(vol[has]))
            record[f"volume_median_{ph}"] = cut
            idx = np.flatnonzero(m)[has]
            liquidity[idx] = np.where(f["volume"][idx] <= cut, "low", "high")
        record["n_volume_absent"] = int((grp & (liquidity == ABSENT)).sum())
        cuts[f"{sport}/{season}"] = record
    f["phase"] = phase
    f["liquidity"] = liquidity
    f["cell"] = np.array([f"{p}/{q}" if q else "" for p, q in
                          zip(phase, liquidity, strict=True)], dtype=object)
    return cuts


def null_reference(sport: str, n: int) -> dict:
    """The null ECE p99 and slope CI to judge a sample of size `n` against.

    Picks the largest tabulated n at or below the sample's, so the reference is
    never NARROWER than the sample deserves. The reference n travels with the
    value, because "ECE 0.09 against a null of 0.1288 at n=225" is the whole
    content of a per-cell calibration claim and the bare 0.09 says nothing.

    **Below the smallest tabulated n the reference is ANTI-conservative**, since
    a smaller sample has a wider null than any row can supply. That is flagged
    as `below_table`, and the fix is to simulate the row rather than to lean on
    the flag: NBA cells reach n=212 (the late cells lose the 161 games with no
    volume), so an n=200 row was simulated in week 5 precisely to keep every
    real cell inside the table.
    """
    rows = sorted(m for (s, m) in CENSUS_NULL_ECE_P99_BY_N if s == sport)
    if not rows:
        raise ValueError(f"no null reference rows for sport {sport!r}")
        # sports are nba/nhl; anything else is a typo, not a new sport
    at_or_below = [m for m in rows if m <= n]
    ref = max(at_or_below) if at_or_below else min(rows)
    return {"reference_n": ref,
            "below_table": not at_or_below,
            "ece_p99": CENSUS_NULL_ECE_P99_BY_N[(sport, ref)],
            "slope_ci": CENSUS_NULL_SLOPE_CI_BY_N[(sport, ref)]}


def _fit(p: np.ndarray, y: np.ndarray) -> tuple[float | None, float | None, str | None]:
    try:
        slope, intercept = cox_slope_intercept(p, y)
    except ValueError as e:
        return None, None, str(e)
    return slope, intercept, None


def cell_stats(p: np.ndarray, y: np.ndarray, sport: str) -> dict:
    """Everything reported for one cell, with its own-n null beside it."""
    n_bins = n_bins_for(len(p))
    slope, intercept, err = _fit(p, y)
    null = null_reference(sport, len(p))
    out = {
        "n": len(p),
        "n_bins": n_bins,
        "brier": brier(p, y),
        "ece_10bin": ece(p, y, MAX_BINS),
        "cox_slope": slope,
        "cox_intercept": intercept,
        "cox_error": err,
        "home_win_rate": float(y.mean()),
        "mean_price": float(p.mean()),
        # At MAX_BINS, not n_bins: a cell of ~300 games gets n_bins_for = 1 or 2,
        # and resolution with ONE bin is identically 0 because every game sits in
        # the same bin. The printed 0.0000 was an artifact of the bin count, not
        # a market with no resolving power. 10 bins is noisy at n~300 and is
        # reported as comparable-but-noisy rather than as a precise quantity.
        "resolution": murphy(p, y, MAX_BINS)["resolution"],
        "null": null,
    }
    # A per-cell ECE inside its own null is not evidence of calibration; it is
    # the absence of evidence either way. Recorded as such rather than as a pass.
    out["ece_inside_own_null"] = out["ece_10bin"] <= null["ece_p99"]
    out["slope_inside_own_null"] = (
        slope is not None and null["slope_ci"][0] <= slope <= null["slope_ci"][1])
    return out


def cell_table(f: dict, look_name: str = "p_close") -> list[dict]:
    """One row per (sport, season, phase, liquidity) cell, plus phase totals."""
    rows = []
    pairs = sorted({(s, se) for s, se in zip(f["sport"], f["season"], strict=True)})
    for sport, season in pairs:
        base = (f["sport"] == sport) & (f["season"] == season)
        for ph in PHASES:
            for lv in LEVELS:
                m = base & (f["phase"] == ph) & (f["liquidity"] == lv)
                p, y = f[look_name][m], f["y"][m]
                keep = ~np.isnan(p)
                if keep.sum() == 0:
                    continue
                rows.append({"sport": sport, "season": season, "phase": ph,
                             "liquidity": lv, "look": look_name,
                             **cell_stats(p[keep], y[keep], sport)})
    return rows


def slope_difference(p_low: np.ndarray, y_low: np.ndarray,
                     p_high: np.ndarray, y_high: np.ndarray, *,
                     reps: int = 4000, seed: int = 0, alpha: float = 0.05) -> dict:
    """Cox slope difference (low minus high liquidity) with a game bootstrap.

    The bootstrap is STRATIFIED: each liquidity group is resampled to its own
    size, which is what "resample games, not rows" means for a two-group
    contrast and keeps the group sizes of the design fixed.

    Replicates whose fit will not converge are counted, and above
    MAX_COX_FAILURE_RATE the interval is refused rather than returned
    conditioned on convergence.
    """
    slope_low, _, err_low = _fit(p_low, y_low)
    slope_high, _, err_high = _fit(p_high, y_high)
    if slope_low is None or slope_high is None:
        return {"slope_low": slope_low, "slope_high": slope_high,
                "difference": None, "error": err_low or err_high,
                "n_low": len(p_low), "n_high": len(p_high)}

    rng = np.random.default_rng(seed)
    diffs, failed = [], 0
    for _ in range(reps):
        i = rng.integers(0, len(p_low), len(p_low))
        j = rng.integers(0, len(p_high), len(p_high))
        lo, _, _ = _fit(p_low[i], y_low[i])
        hi, _, _ = _fit(p_high[j], y_high[j])
        if lo is None or hi is None:
            failed += 1
            continue
        diffs.append(lo - hi)
    if failed > MAX_COX_FAILURE_RATE * reps:
        raise ValueError(
            f"{failed} of {reps} bootstrap replicates had no computable fit "
            f"({failed / reps:.1%}); the interval would be conditioned on "
            f"convergence and is not returned")
    d = np.asarray(diffs)
    observed = slope_low - slope_high
    return {
        "slope_low": slope_low, "slope_high": slope_high,
        "difference": float(observed),
        "ci_lo": float(np.percentile(d, 100 * alpha / 2)),
        "ci_hi": float(np.percentile(d, 100 * (1 - alpha / 2))),
        # The share of replicates that do not reproduce the observed sign.
        #
        # NOT a p-value, and no longer named like one. It is computed under the
        # OBSERVED distribution, not under the null, so it is an achieved
        # significance level: the bootstrap analogue, not the thing itself.
        # It is also floored at 1/reps -- zero crossings can only ever mean
        # "< 1/reps", never 0 -- so the floor travels with it and a reader
        # cannot mistake 0.0 for exactly zero. Reported beside the interval,
        # never instead of it.
        "bootstrap_asl": float(np.mean(d <= 0) if observed > 0 else np.mean(d >= 0)),
        "bootstrap_asl_floor": 1.0 / reps,
        "excludes_zero": bool(np.percentile(d, 100 * alpha / 2) > 0
                              or np.percentile(d, 100 * (1 - alpha / 2)) < 0),
        "n_low": len(p_low), "n_high": len(p_high),
        "reps": reps, "cox_failures": failed,
    }


def _liquidity_samples(f: dict, sport: str, look_name: str,
                       season: str | None = None, mask: np.ndarray | None = None):
    m = f["sport"] == sport
    if season:
        m = m & (f["season"] == season)
    if mask is not None:
        m = m & mask
    have = m & ~np.isnan(f[look_name])
    out = []
    for lv in LEVELS:
        sel = have & (f["liquidity"] == lv)
        out.append((f[look_name][sel], f["y"][sel]))
    return out[0] + out[1]   # p_low, y_low, p_high, y_high


def primary_test(f: dict, *, sport: str = PRIMARY_SPORT, look_name: str = "p_close",
                 reps: int = 4000, seed: int = 0) -> dict:
    """THE pre-registered primary test: slope difference by liquidity, NBA.

    Pooled across both NBA seasons, because each game's liquidity label is
    already relative to its own season and phase, so pooling does not mix
    regimes. Section 1 still requires the per-season numbers, which
    `per_season` carries, and they are secondary by the section-7 family-wise
    policy along with every other comparison in this module.
    """
    p_low, y_low, p_high, y_high = _liquidity_samples(f, sport, look_name)
    result = slope_difference(p_low, y_low, p_high, y_high, reps=reps, seed=seed)
    seasons = sorted({s for s, sp in zip(f["season"], f["sport"], strict=True)
                      if sp == sport})
    per_season = {}
    for season in seasons:
        pl, yl, ph, yh = _liquidity_samples(f, sport, look_name, season=season)
        per_season[season] = slope_difference(pl, yl, ph, yh, reps=reps, seed=seed)
    return {"sport": sport, "look": look_name, "pooled": result,
            "per_season": per_season,
            "primary": True,
            "null_reference_low": null_reference(sport, len(p_low)),
            "null_reference_high": null_reference(sport, len(p_high))}


PRICE_BANDS = ((0.20, 0.80), (0.35, 0.65))
CALIPER = 0.10


def caliper_match(f: dict, sport: str, look_name: str = "p_close",
                  caliper: float = CALIPER) -> tuple[np.ndarray, np.ndarray]:
    """1:1 match low to high liquidity on |logit p|, so both share a price spread.

    **Why this exists.** Volume is outcome-correlated, which section 8 flags:
    close games attract volume. Measured on NBA, high-liquidity games really do
    sit nearer 0.5 (sd of logit p 0.949 against 1.207; 50.7% inside [0.35, 0.65]
    against 31.5%). A Cox slope fitted over a narrower price range attenuates,
    so the entire stratum contrast could be a range artifact rather than a
    calibration difference. Matching equalises the spread and asks again.

    Greedy nearest neighbour over the sorted high-liquidity side, without
    replacement, rejecting pairs further apart than `caliper`. Deterministic:
    the frame is in canonical order and no randomness is involved, so the
    matched set is reproducible.
    """
    from scipy.special import logit as _logit
    m = (f["sport"] == sport) & ~np.isnan(f[look_name])
    lg = np.abs(_logit(np.clip(f[look_name], LOGIT_EPS, 1 - LOGIT_EPS)))
    low = np.flatnonzero(m & (f["liquidity"] == "low"))
    high = np.flatnonzero(m & (f["liquidity"] == "high"))
    order = np.argsort(lg[high], kind="stable")
    high_sorted, high_vals = high[order], lg[high][order]
    used = np.zeros(len(high_sorted), dtype=bool)
    pairs: list[tuple[int, int]] = []
    for i in low:
        target = lg[i]
        pos = int(np.searchsorted(high_vals, target))
        best, best_d = -1, np.inf
        # walk outward from the insertion point until the caliper is exceeded
        left, right = pos - 1, pos
        while left >= 0 or right < len(high_sorted):
            for q in (right, left):
                if 0 <= q < len(high_sorted) and not used[q]:
                    d = abs(high_vals[q] - target)
                    if d < best_d:
                        best, best_d = q, d
            nearest_possible = min(
                abs(high_vals[right] - target) if right < len(high_sorted) else np.inf,
                abs(high_vals[left] - target) if left >= 0 else np.inf)
            if best_d <= nearest_possible or nearest_possible > caliper:
                break
            left -= 1
            right += 1
        if best >= 0 and best_d <= caliper:
            used[best] = True
            pairs.append((i, int(high_sorted[best])))
    if not pairs:
        return np.array([], dtype=int), np.array([], dtype=int)
    return (np.array([a for a, _ in pairs]), np.array([b for _, b in pairs]))


def range_sensitivity(f: dict, *, sport: str = PRIMARY_SPORT,
                      look_name: str = "p_close", reps: int = 2000,
                      seed: int = 0) -> dict:
    """Is the stratum contrast just a price-range difference? Exploratory."""
    out: dict = {"dispersion": {}, "bands": {}, "caliper_matched": {}}
    from scipy.special import logit as _logit
    for lv in LEVELS:
        m = (f["sport"] == sport) & (f["liquidity"] == lv) & ~np.isnan(f[look_name])
        p = f[look_name][m]
        out["dispersion"][lv] = {
            "n": int(m.sum()),
            "sd_logit_price": float(np.std(_logit(np.clip(p, LOGIT_EPS,
                                                          1 - LOGIT_EPS)))),
            "share_inside_0.35_0.65": float(np.mean((p >= 0.35) & (p <= 0.65))),
            "mean_abs_dist_from_half": float(np.mean(np.abs(p - 0.5))),
        }
    for lo, hi in PRICE_BANDS:
        band = (f[look_name] >= lo) & (f[look_name] <= hi)
        pl, yl, ph, yh = _liquidity_samples(f, sport, look_name, mask=band)
        if len(pl) and len(ph):
            out["bands"][f"{lo}-{hi}"] = slope_difference(pl, yl, ph, yh, reps=reps,
                                                          seed=seed)
    il, ih = caliper_match(f, sport, look_name)
    if len(il):
        out["caliper_matched"] = {
            "pairs": len(il),
            "caliper": CALIPER,
            "sd_logit_low": float(np.std(np.abs(_logit(np.clip(
                f[look_name][il], LOGIT_EPS, 1 - LOGIT_EPS))))),
            "sd_logit_high": float(np.std(np.abs(_logit(np.clip(
                f[look_name][ih], LOGIT_EPS, 1 - LOGIT_EPS))))),
            **slope_difference(f[look_name][il], f["y"][il],
                               f[look_name][ih], f["y"][ih], reps=reps, seed=seed),
        }
    return out


def sensitivity(f: dict, *, sport: str = PRIMARY_SPORT, reps: int = 2000,
                seed: int = 0) -> dict:
    """Every pre-registered robustness split. All exploratory, never headline.

    The four time-to-close looks are four looks at ONE sample, so they are
    reported as separate intervals and never combined into one: a single
    interval over the four would be too narrow by construction (section 8).
    """
    out: dict = {"by_look": {}, "by_staleness": {}, "volume_absent": {},
                 "price_range": range_sensitivity(f, sport=sport, reps=reps,
                                                  seed=seed)}
    for look_name in ("p_close", "p_t1h", "p_t6h", "p_t24h"):
        pl, yl, ph, yh = _liquidity_samples(f, sport, look_name)
        if len(pl) == 0 or len(ph) == 0:
            continue
        out["by_look"][look_name] = slope_difference(pl, yl, ph, yh, reps=reps,
                                                     seed=seed)
    stale = np.array([bool(v) for v in f["stale_flat_run"]])
    for label, mask in (("stale", stale), ("fresh", ~stale)):
        pl, yl, ph, yh = _liquidity_samples(f, sport, "p_close", mask=mask)
        if len(pl) == 0 or len(ph) == 0:
            continue
        out["by_staleness"][label] = slope_difference(pl, yl, ph, yh, reps=reps,
                                                      seed=seed)
    # Amendment 3c required a re-run with proxied games excluded. Amendment 4
    # withdrew the proxy, so there are none: the split is reported as the count
    # of games the liquidity axis never saw, which is the honest equivalent.
    absent = f["liquidity"] == ABSENT
    out["volume_absent"] = {
        "n": int(absent.sum()),
        "by_sport_season": {
            f"{s}/{se}": int(((f["sport"] == s) & (f["season"] == se) & absent).sum())
            for s, se in sorted({(a, b) for a, b in
                                 zip(f["sport"], f["season"], strict=True)})},
        "weeks": sorted({int(w) for w in f["week_of_season"][absent]}),
        "note": "excluded from the liquidity axis, never proxied (Amendment 4); "
                "still present in the phase axis and in every unstratified number",
    }
    return out
