"""Cut the two Phase 2 charts from the immutable snapshot.

    uv run python scripts/make_charts.py

Reads only `data/snapshots/census-*` (verifying every checksum first), never the
store and never the API. Writes PNGs plus the JSON behind them to docs/charts/,
which is whitelisted in .gitignore: these are DERIVED AGGREGATES (curves, bin
counts, decompositions), which notes/week1-tos-check.md identifies as carrying
no redistribution question, unlike the raw minute series.

Chart 1 decides the primary sport. Chart 2 is a reported result and has NO gate
authority (PREREGISTRATION.md section 4).
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from chira.analysis import open_frame
from chira.charts import chart_calibration, chart_coverage


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None,
                    help="defaults to the newest data/snapshots/census-*")
    ap.add_argument("--out", default="docs/charts")
    ap.add_argument("--reps", type=int, default=2000,
                    help="bootstrap replicates; games are resampled, never rows")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip snapshot checksums (faster; not for a quoted result)")
    args = ap.parse_args()

    snaps = sorted(glob.glob("data/snapshots/census-*"))
    if not args.snapshot and not snaps:
        print("no snapshot found; run scripts/make_snapshot.py first")
        return 2
    snap = args.snapshot or snaps[-1]
    con = open_frame(snap, verify=not args.no_verify)
    out = Path(args.out)
    manifest = json.loads((Path(snap) / "manifest.json").read_text(encoding="utf-8"))
    print(f"snapshot: {snap}")
    print(f"store digest: {manifest['store_digest']}")

    cov = chart_coverage(con, out / "chart1-coverage.png")
    print("\nCHART 1 — coverage by week of season")
    for key, s in cov.items():
        w = s["worst_week"]
        print(f"  {key:16} {s['priced']}/{s['scheduled']} ({s['coverage']:.1%})  "
              f"worst week {w['week']} ({w['week_start']}): "
              f"{w['priced']}/{w['scheduled']}  volume absent on {s['volume_missing']}")

    cal = chart_calibration(con, out / "chart2-calibration.png", reps=args.reps)
    print("\nCHART 2 — the market's own calibration at the close")
    for key, s in cal.items():
        b = s["bootstrap"]
        if s["cox_slope"] is None:
            cox = f"cox fit DEGENERATE ({s['cox_error']})"
        else:
            cox = (f"slope {s['cox_slope']:.3f} "
                   f"[{b['slope']['lo']:.3f}, {b['slope']['hi']:.3f}]  "
                   f"intercept {s['cox_intercept']:+.4f} "
                   f"[{b['intercept']['lo']:+.4f}, {b['intercept']['hi']:+.4f}]")
        print(f"  {key:16} n={s['n']:<5} bins={s['n_bins']}  Brier {s['brier']:.4f}  "
              f"ECE(10) {s['ece_10bin']:.4f}  {cox}")
        m = s["murphy"]
        print(f"  {'':16} Murphy: reliability {m['reliability']:.5f}  "
              f"resolution {m['resolution']:.5f}  uncertainty {m['uncertainty']:.5f}  "
              f"home win rate {s['home_win_rate']:.4f}")

    payload = {
        "snapshot": snap,
        "store_digest": manifest["store_digest"],
        "census_git_hash": manifest["git_hash"],
        "bootstrap_reps": args.reps,
        "coverage": cov,
        "calibration_close": cal,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "chart-data.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nwrote {out}/chart1-coverage.png, {out}/chart2-calibration.png, "
          f"{out}/chart-data.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
