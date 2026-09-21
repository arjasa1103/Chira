"""The two Phase 2 charts.

Chart 1 decides the project: coverage by week of season, per sport-season, with
the median-volume panel underneath. Chart 2 is the market's own calibration
curve, and it is a **REPORTED RESULT, NOT A GATE** (PREREGISTRATION.md
section 4, PLAN.md Phase 2). The earlier framing said a miscalibrated market
means a broken pipeline; that inference is invalid, because a miscalibrated
result is ambiguous between a bug and headline 2's actual finding. Pipeline
validity comes from the seven census-gate checks, which do not assume the
market is calibrated.

Two bin counts appear here on purpose:

- The **curve** uses `n_bins_for`, honouring the pre-registered 150-games-per-bin
  floor, so the plotted shape is not noise.
- The **ECE quoted against `GATE_ECE_MAX`** uses 10 bins, because the section-4
  noise floor was simulated at 10 bins and a threshold is only comparable to
  the null it came from.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display in CI, and none wanted: these are files
import matplotlib.pyplot as plt
import numpy as np

from .analysis import coverage_by_week, frame, look, look_coverage, sport_seasons
from .calibration import (
    MAX_BINS,
    binned_curve,
    bootstrap_curve,
    bootstrap_scalars,
    brier,
    cox_slope_intercept,
    ece,
    murphy,
    n_bins_for,
    quantile_bin_edges,
)
from .constants import GATE_ECE_MAX, GATE_INTERCEPT_BAND, GATE_SLOPE_BAND

PRICED_COLOR = "#2f6f9f"
MISSED_COLOR = "#c8553d"
BAND_COLOR = "#2f6f9f"
LABEL = {"nba": "NBA", "nhl": "NHL"}


def _title(sport: str, season: str) -> str:
    return f"{LABEL.get(sport, sport)} {season}"


def chart_coverage(con, out: str | Path) -> dict:
    """Chart 1: coverage by week of season, stacked, plus median volume.

    Stacked bars are scheduled games split into priced and missed, so the bar
    height is the schedule itself and a missing market is visible as red rather
    than as a shorter bar (a shorter bar reads as "fewer games that week").
    """
    pairs = sport_seasons(con)
    fig, axes = plt.subplots(2, len(pairs), figsize=(4.6 * len(pairs), 7.2),
                             sharex="col", gridspec_kw={"height_ratios": [2, 1]})
    if len(pairs) == 1:
        axes = axes.reshape(2, 1)
    summary: dict = {}

    for col, (sport, season) in enumerate(pairs):
        weeks = coverage_by_week(con, sport, season)
        w = [r["week"] for r in weeks]
        priced = np.array([r["priced"] for r in weeks])
        missed = np.array([r["missed"] for r in weeks])
        sched = np.array([r["scheduled"] for r in weeks])

        ax = axes[0][col]
        ax.bar(w, priced, color=PRICED_COLOR, label="market found")
        ax.bar(w, missed, bottom=priced, color=MISSED_COLOR, label="no market")
        ax.set_title(f"{_title(sport, season)}\n{priced.sum()} priced / "
                     f"{sched.sum()} scheduled ({priced.sum() / sched.sum():.1%})")
        ax.set_ylabel("games" if col == 0 else "")
        if col == 0:
            ax.legend(loc="lower right", fontsize=8)

        axv = axes[1][col]
        med = [r["median_volume"] for r in weeks]
        # Weeks with no priced game have no median at all; plotting 0 there
        # would draw a cliff that is an absence, not a thin market.
        wx = [x for x, m in zip(w, med, strict=True) if m is not None]
        wy = [m for m in med if m is not None]
        axv.plot(wx, wy, color=PRICED_COLOR, marker="o", markersize=2.5, linewidth=1)
        axv.set_yscale("log")
        axv.set_xlabel("week of season")
        axv.set_ylabel("median volume ($, log)" if col == 0 else "")
        vmiss = sum(r["volume_missing"] for r in weeks)
        if vmiss:
            axv.set_title(f"volume absent on {vmiss} priced games", fontsize=8)

        summary[f"{sport}/{season}"] = {
            "weeks": weeks,
            "scheduled": int(sched.sum()),
            "priced": int(priced.sum()),
            "missed": int(missed.sum()),
            "coverage": round(float(priced.sum() / sched.sum()), 4),
            "volume_missing": vmiss,
            "worst_week": min(
                ({"week": r["week"], "week_start": r["week_start"],
                  "priced": r["priced"], "scheduled": r["scheduled"]}
                 for r in weeks if r["scheduled"]),
                key=lambda r: r["priced"] / r["scheduled"]),
        }

    fig.suptitle("Chart 1 — Polymarket moneyline coverage by week of season", y=0.99)
    fig.tight_layout()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return summary


def calibration_stats(p: np.ndarray, y: np.ndarray, *, reps: int = 2000,
                      seed: int = 0) -> dict:
    """Every number chart 2 reports for one sample, plus its bootstrap bands."""
    n_bins = n_bins_for(len(p))
    edges = quantile_bin_edges(p, n_bins)
    curve = binned_curve(p, y, edges)
    bands = bootstrap_curve(p, y, edges, reps=reps, seed=seed)
    scal = bootstrap_scalars(p, y, reps=reps, seed=seed)
    # A degenerate sample must not kill the chart run. `cox_slope_intercept`
    # raises rather than returning a meaningless number (week 1: a constant-price
    # sample once reported slope 165.04 as if it were a result), and the
    # per-stratum samples of weeks 5-6 are small enough that a separable one is
    # plausible. So record the failure explicitly and keep going.
    #
    # None, never nan: `nan <= GATE` evaluates False, so a nan would quietly
    # "fail" a gate it never actually computed, while None raises if compared.
    try:
        slope, intercept = cox_slope_intercept(p, y)
        cox_error = None
    except ValueError as e:
        slope, intercept, cox_error = None, None, str(e)
    # Absent when EVERY bootstrap replicate's fit was degenerate.
    slope_ci, intercept_ci = scal.get("slope"), scal.get("intercept")
    return {
        "n": len(p),
        "n_bins": n_bins,
        "curve": {k: v.tolist() for k, v in curve.items()},
        "band_lo": bands["lo"].tolist(),
        "band_hi": bands["hi"].tolist(),
        "brier": brier(p, y),
        # 10 bins: the only count comparable to the section-4 null.
        "ece_10bin": ece(p, y, MAX_BINS),
        "ece_chart_bins": ece(p, y, n_bins),
        "murphy": murphy(p, y, n_bins),
        "cox_slope": slope,
        "cox_intercept": intercept,
        "cox_error": cox_error,
        "bootstrap": scal,
        "home_win_rate": float(y.mean()),
        "mean_price": float(p.mean()),
        # The section-4 EQUIVALENCE form: the CI must lie ENTIRELY inside the
        # band. Recorded, never enforced here -- the market has no gate authority.
        # A sample with no computable CI is NOT inside the band; "we could not
        # measure it" must never read as "it passed".
        "slope_ci_inside_band": bool(
            slope_ci is not None
            and GATE_SLOPE_BAND[0] <= slope_ci["lo"]
            and slope_ci["hi"] <= GATE_SLOPE_BAND[1]),
        "intercept_ci_inside_band": bool(
            intercept_ci is not None
            and GATE_INTERCEPT_BAND[0] <= intercept_ci["lo"]
            and intercept_ci["hi"] <= GATE_INTERCEPT_BAND[1]),
        "ece_10bin_within_gate": bool(ece(p, y, MAX_BINS) <= GATE_ECE_MAX),
    }


def chart_calibration(con, out: str | Path, *, look_name: str = "p_close",
                      reps: int = 2000, seed: int = 0) -> dict:
    """Chart 2: the market's calibration curve, home side, one row per game."""
    pairs = sport_seasons(con)
    ncol = len(pairs)
    fig, axes = plt.subplots(1, ncol, figsize=(4.2 * ncol, 4.6), sharey=True)
    axes = np.atleast_1d(axes)
    stats: dict = {}

    for ax, (sport, season) in zip(axes, pairs, strict=True):
        f = frame(con, sport, season)
        p, y = look(f, look_name)
        s = calibration_stats(p, y, reps=reps, seed=seed)
        stats[f"{sport}/{season}"] = {**s, "look_coverage": look_coverage(f)}

        mp = np.array(s["curve"]["mean_p"])
        obs = np.array(s["curve"]["obs_rate"])
        ax.plot([0, 1], [0, 1], color="0.6", linewidth=1, linestyle="--",
                label="perfect calibration")
        ax.fill_between(mp, s["band_lo"], s["band_hi"], color=BAND_COLOR,
                        alpha=0.22, label="95% bootstrap band")
        ax.plot(mp, obs, color=BAND_COLOR, marker="o", markersize=4, linewidth=1.2,
                label="observed")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_aspect("equal")
        ax.set_xlabel("market closing price (home)")
        if s["cox_slope"] is None:
            slope_txt = "slope: degenerate fit"
        else:
            ci = s["bootstrap"].get("slope")
            span = f" [{ci['lo']:.3f}, {ci['hi']:.3f}]" if ci else ""
            slope_txt = f"slope {s['cox_slope']:.3f}{span}"
        ax.set_title(f"{_title(sport, season)}  n={s['n']}\n"
                     f"Brier {s['brier']:.4f}  ECE {s['ece_10bin']:.4f}\n"
                     f"{slope_txt}", fontsize=9)

    axes[0].set_ylabel("observed home win rate")
    axes[0].legend(loc="upper left", fontsize=7)
    fig.suptitle("Chart 2 — the market's own calibration at the close "
                 "(a reported result, not a gate)", y=1.0)
    fig.tight_layout()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return stats


def chart_strata(f: dict, out: str | Path, *, sport: str = "nba",
                 look_name: str = "p_close", reps: int = 2000,
                 seed: int = 0) -> dict:
    """Chart 3: headline 2. Calibration by liquidity, and every cell's slope.

    Left panel is the pre-registered contrast: two calibration curves, low and
    high liquidity, for the sport the primary test runs on. Right panel is every
    cell's Cox slope against the null band AT THAT CELL'S OWN n, which is the
    only honest way to read a per-cell slope: at NHL n=225 a perfectly
    calibrated market's slope can sit anywhere in [0.414, 1.694].
    """
    from .strata import LEVELS, cell_table, null_reference, primary_test

    fig, (ax, axf) = plt.subplots(1, 2, figsize=(12.5, 5.6),
                                  gridspec_kw={"width_ratios": [1, 1.25]})
    colors = {"low": "#c8553d", "high": "#2f6f9f"}
    stats = {}
    ax.plot([0, 1], [0, 1], color="0.6", lw=1, ls="--", label="perfect calibration")
    for lv in LEVELS:
        m = (f["sport"] == sport) & (f["liquidity"] == lv) & ~np.isnan(f[look_name])
        p, y = f[look_name][m], f["y"][m]
        s = calibration_stats(p, y, reps=reps, seed=seed)
        stats[lv] = s
        mp = np.array(s["curve"]["mean_p"])
        ax.fill_between(mp, s["band_lo"], s["band_hi"], color=colors[lv], alpha=0.18)
        ax.plot(mp, np.array(s["curve"]["obs_rate"]), color=colors[lv], marker="o",
                ms=4, lw=1.4,
                label=f"{lv} liquidity (n={s['n']}, slope {s['cox_slope']:.2f})")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.set_xlabel("market closing price (home)")
    ax.set_ylabel("observed home win rate")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_title(f"{LABEL.get(sport, sport)}: calibration by liquidity", fontsize=10)

    cells = cell_table(f, look_name)
    ys = np.arange(len(cells))
    for i, r in enumerate(cells):
        lo, hi = r["null"]["slope_ci"]
        # the null band first, so a slope inside it is visibly unremarkable
        axf.plot([lo, hi], [i, i], color="0.75", lw=6, solid_capstyle="butt",
                 zorder=1)
        if r["cox_slope"] is not None:
            axf.plot(r["cox_slope"], i, "o", ms=6, zorder=2,
                     color=colors.get(r["liquidity"], "0.3"))
    axf.axvline(1.0, color="0.4", lw=1, ls="--")
    axf.set_yticks(ys)
    axf.set_yticklabels([f"{r['sport']} {r['season']} {r['phase']}/{r['liquidity']}"
                         for r in cells], fontsize=7)
    axf.set_xlabel("Cox slope (grey = null 95% band at that cell's own n)")
    axf.set_title("every cell, against its own noise floor", fontsize=10)
    axf.invert_yaxis()

    prim = primary_test(f, sport=sport, look_name=look_name, reps=reps, seed=seed)
    pooled = prim["pooled"]
    fig.suptitle(
        f"Chart 3 — headline 2: slope difference (low - high liquidity) "
        f"{pooled['difference']:+.3f}  95% CI "
        f"[{pooled['ci_lo']:+.3f}, {pooled['ci_hi']:+.3f}]", y=0.99)
    fig.tight_layout()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return {"by_liquidity": stats, "primary": prim,
            "null_at_primary_n": null_reference(sport, pooled["n_low"])}
