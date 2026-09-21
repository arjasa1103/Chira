"""Headline 2: stratified market calibration (T9).

    uv run python scripts/run_headline2.py

Reads the frozen snapshot plus the volume side table, builds the pre-registered
2x2 (PREREGISTRATION.md section 8, Amendments 3a/3b/4), runs THE primary
directional test and every robustness split, and writes docs/charts/headline2.json.

The primary test is one number with one interval: the Cox slope difference
between liquidity strata, NBA, at the close. Everything else printed here is
exploratory under the section-7 family-wise policy, and is labelled so.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from chira.analysis import frame, open_frame
from chira.charts import chart_strata
from chira.strata import (
    assign_strata,
    cell_table,
    primary_test,
    sensitivity,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--out", default="docs/charts/headline2.json")
    ap.add_argument("--reps", type=int, default=4000)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    snap = args.snapshot or sorted(glob.glob("data/snapshots/census-*"))[-1]
    con = open_frame(snap, verify=not args.no_verify)
    manifest = json.loads((Path(snap) / "manifest.json").read_text(encoding="utf-8"))
    f = frame(con)
    cuts = assign_strata(f)

    print(f"snapshot: {snap}\nstore digest: {manifest['store_digest']}\n")
    print("=== CUT POINTS (within each sport-season) ===")
    for key, c in cuts.items():
        print(f"  {key:14} week median {c['week_median']:>5}  "
              f"volume median early {c['volume_median_early']:>12,.0f}  "
              f"late {c['volume_median_late']:>12,.0f}  "
              f"no volume {c['n_volume_absent']:>4}")

    cells = cell_table(f)
    print("\n=== CELLS (close, each judged against the null at ITS OWN n) ===")
    print(f"  {'cell':30} {'n':>5} {'slope':>8} {'ECE':>7} {'null ECE':>9} "
          f"{'null slope CI':>18} {'res':>7}")
    for r in cells:
        slope = f"{r['cox_slope']:+.3f}" if r["cox_slope"] is not None else "  FAIL"
        lo, hi = r["null"]["slope_ci"]
        print(f"  {r['sport']+'/'+r['season']+' '+r['phase']+'/'+r['liquidity']:30} "
              f"{r['n']:5} {slope:>8} {r['ece_10bin']:7.4f} {r['null']['ece_p99']:9.4f} "
              f"{'['+format(lo,'.3f')+', '+format(hi,'.3f')+']':>18} "
              f"{r['resolution']:7.4f}")

    prim = primary_test(f, reps=args.reps)
    pooled = prim["pooled"]
    print("\n=== PRIMARY TEST (pre-registered, NBA, close) ===")
    print(f"  slope low liquidity  {pooled['slope_low']:+.4f}  (n={pooled['n_low']})")
    print(f"  slope high liquidity {pooled['slope_high']:+.4f}  (n={pooled['n_high']})")
    print(f"  difference (low - high) {pooled['difference']:+.4f}  "
          f"95% CI [{pooled['ci_lo']:+.4f}, {pooled['ci_hi']:+.4f}]")
    print(f"  excludes zero: {pooled['excludes_zero']}   "
          f"one-sided p = {pooled['p_one_sided']:.4f}   "
          f"failed replicates {pooled['cox_failures']}/{pooled['reps']}")
    print("  per season (secondary):")
    for season, r in prim["per_season"].items():
        if r["difference"] is None:
            print(f"    {season}: fit failed ({r['error'][:50]})")
            continue
        print(f"    {season}: {r['difference']:+.4f} "
              f"[{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}] "
              f"excludes zero {r['excludes_zero']}")

    sens = sensitivity(f, reps=max(500, args.reps // 4))
    print("\n=== SENSITIVITY (all exploratory) ===")
    for look_name, r in sens["by_look"].items():
        if r["difference"] is None:
            continue
        print(f"  {look_name:9} diff {r['difference']:+.4f} "
              f"[{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}] "
              f"n={r['n_low']}/{r['n_high']} excludes zero {r['excludes_zero']}")
    for label, r in sens["by_staleness"].items():
        if r["difference"] is None:
            continue
        print(f"  {label:9} diff {r['difference']:+.4f} "
              f"[{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}] "
              f"n={r['n_low']}/{r['n_high']} excludes zero {r['excludes_zero']}")
    pr = sens["price_range"]
    print("  price-range artifact check (volume is outcome-correlated):")
    for lv, d in pr["dispersion"].items():
        print(f"    {lv:5} sd(logit p) {d['sd_logit_price']:.3f}  "
              f"inside[.35,.65] {d['share_inside_0.35_0.65']:.3f}")
    for band, r in pr["bands"].items():
        print(f"    band {band:9} diff {r['difference']:+.4f} "
              f"[{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}] n={r['n_low']}/{r['n_high']} "
              f"excludes zero {r['excludes_zero']}")
    cm = pr["caliper_matched"]
    if cm:
        print(f"    caliper-matched {cm['pairs']} pairs "
              f"(sd {cm['sd_logit_low']:.3f} vs {cm['sd_logit_high']:.3f}): "
              f"diff {cm['difference']:+.4f} [{cm['ci_lo']:+.4f}, {cm['ci_hi']:+.4f}] "
              f"excludes zero {cm['excludes_zero']}")
    va = sens["volume_absent"]
    print(f"  volume absent: {va['n']} games excluded from the liquidity axis "
          f"{va['by_sport_season']}, weeks {va['weeks'][:4]}...{va['weeks'][-2:]}")

    chart = Path(args.out).parent / "chart3-headline2.png"
    chart_strata(f, chart, reps=min(args.reps, 2000))
    print(f"\nwrote {chart}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "snapshot": snap,
        "store_digest": manifest["store_digest"],
        "cuts": cuts,
        "cells": cells,
        "primary_test": prim,
        "sensitivity": sens,
        "bootstrap_reps": args.reps,
    }, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
