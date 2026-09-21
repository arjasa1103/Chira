"""Re-derive the section-4 null bands from the REAL census price pools.

    uv run python scripts/derive_null_bands.py

PREREGISTRATION.md section 4 closes with an explicit obligation:

    The null was bootstrapped from a measured NBA-only pool (n=128). NHL prices
    are markedly more concentrated ... the pool must be re-measured once real
    NHL census prices exist, and the NHL-only band re-derived rather than
    inherited.

This discharges it. A more concentrated pool puts more games near 0.5, where
Bernoulli variance is highest, so the null is WIDER for NHL and an adopted
bound that covers NBA does not automatically cover NHL. The outcome that
matters is whether any adopted GATE_* constant now sits INSIDE the NHL null,
which would mean the gate false-fires on a correct NHL pipeline.

Writes data/noise_floor_census.json. Outcomes are drawn as y ~ Bernoulli(p), so
the simulated market is perfectly calibrated by construction and no census
outcome is touched: this measures the estimator, not the market.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys

import numpy as np

sys.path.insert(0, "src")
from chira.analysis import open_frame, price_pool
from chira.calibration import simulate_null
from chira.constants import (
    GATE_ECE_MAX,
    GATE_INTERCEPT_BAND,
    GATE_MAX_BIN_DEV,
    GATE_SLOPE_BAND,
)

# n values that a real analysis will actually run at, per pool.
#
# The small ones are headline-2's strata (PREREGISTRATION.md section 8 and
# Amendment 3a): a 2x2 of liquidity x season phase splits each sport-season into
# four cells of 221-312 games, and each stratum half is 448-615. Section 4
# forbids judging those against the pooled cap, and the week-1 table stopped at
# n=850, so nothing covered per-cell n until these rows existed.
NS = {
    "nba": (200, 300, 613, 1226, 2455),
    "nhl": (200, 225, 300, 448, 615, 896, 1310, 2206),
    "all": (4661,),
}


def pool_shape(p: np.ndarray) -> dict:
    """Why one pool's null is wider than another's, in two numbers."""
    return {
        "n_pool": len(p),
        "share_inside_0.35_0.65": round(float(np.mean((p >= 0.35) & (p <= 0.65))), 4),
        "expected_p_1_minus_p": round(float(np.mean(p * (1 - p))), 4),
        "min": float(p.min()), "max": float(p.max()),
    }


def breaches(null: dict) -> list[str]:
    """Adopted constants that sit INSIDE this null, i.e. would false-fire.

    Only meaningful at the POOLED FULL-CENSUS n. PREREGISTRATION.md section 4
    adopts these four constants "evaluated on the FULL census", and states that
    "per-stratum and per-bin analyses use the corresponding row of the table
    above, never the n=5,084 numbers". So a per-season null exceeding a
    pooled-census constant is not a breach; it is the per-n reference row that
    section 4 requires such analyses to use, and comparing the two would be
    applying a bound at an n it was never adopted for.
    """
    bad = []
    if null["ece"]["p99"] > GATE_ECE_MAX:
        bad.append(f"ECE p99 {null['ece']['p99']:.4f} > GATE_ECE_MAX {GATE_ECE_MAX}")
    if null["max_bin_dev"]["p99"] > GATE_MAX_BIN_DEV:
        bad.append(f"max_bin_dev p99 {null['max_bin_dev']['p99']:.4f} > "
                   f"GATE_MAX_BIN_DEV {GATE_MAX_BIN_DEV}")
    lo, hi = GATE_SLOPE_BAND
    if not (lo <= null["slope"]["lo2.5"] and null["slope"]["hi97.5"] <= hi):
        bad.append(f"slope null CI [{null['slope']['lo2.5']:.4f}, "
                   f"{null['slope']['hi97.5']:.4f}] escapes GATE_SLOPE_BAND {GATE_SLOPE_BAND}")
    lo, hi = GATE_INTERCEPT_BAND
    if not (lo <= null["intercept"]["lo2.5"] and null["intercept"]["hi97.5"] <= hi):
        bad.append(f"intercept null CI [{null['intercept']['lo2.5']:.4f}, "
                   f"{null['intercept']['hi97.5']:.4f}] escapes "
                   f"GATE_INTERCEPT_BAND {GATE_INTERCEPT_BAND}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None,
                    help="defaults to the newest data/snapshots/census-*")
    ap.add_argument("--reps", type=int, default=1500,
                    help="1500 matches the section-4 derivation")
    ap.add_argument("--out", default="data/noise_floor_census.json")
    args = ap.parse_args()

    snap = args.snapshot or sorted(glob.glob("data/snapshots/census-*"))[-1]
    con = open_frame(snap)
    print(f"snapshot: {snap}")

    report: dict = {"snapshot": snap, "reps": args.reps, "pools": {}, "breaches": {},
                    "note": "breaches are evaluated ONLY at the pooled full-census n, "
                            "which is the only n section 4 adopts the constants at; the "
                            "other rows are the per-n reference table for strata"}
    for pool_name, ns in NS.items():
        sport = None if pool_name == "all" else pool_name
        p = price_pool(con, sport)
        report["pools"][pool_name] = {"shape": pool_shape(p), "null": {}}
        print(f"\n{pool_name}: {pool_shape(p)}")
        for n in ns:
            null = simulate_null(p, n=n, reps=args.reps, seed=7)
            report["pools"][pool_name]["null"][str(n)] = null
            # The pooled census row is the ONLY one the adopted constants govern.
            governed = pool_name == "all" and n == max(NS["all"])
            bad = breaches(null) if governed else []
            if bad:
                report["breaches"][f"{pool_name}/n={n}"] = bad
            flag = "  <-- BREACH" if bad else ("  <-- governs the constants"
                                               if governed else "")
            print(f"  n={n:>5}  ECE p99={null['ece']['p99']:.4f}  "
                  f"maxbin p99={null['max_bin_dev']['p99']:.4f}  "
                  f"slope [{null['slope']['lo2.5']:.3f}, {null['slope']['hi97.5']:.3f}]  "
                  f"intercept [{null['intercept']['lo2.5']:.4f}, "
                  f"{null['intercept']['hi97.5']:.4f}]{flag}")
            for b in bad:
                print(f"      {b}")

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    print(f"\nwrote {args.out}")

    if report["breaches"]:
        print("\nADOPTED GATE CONSTANTS FALSE-FIRE ON A CORRECT PIPELINE:")
        for where, bad in report["breaches"].items():
            print(f"  {where}: {'; '.join(bad)}")
        print("These must be widened in constants.py and the change recorded in "
              "PREREGISTRATION.md before any gate verdict is quoted.")
        return 1
    print("\nevery adopted gate constant still sits at or above the re-measured null")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
