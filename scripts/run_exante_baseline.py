"""The ex-ante base rate: a constant forecaster that could have been committed to.

    uv run python scripts/run_exante_baseline.py

Headline 1's NHL caveat compared the model with "the base rate", and the base
rate in `holdout.json` is 2025-26's OWN home-win rate -- a constant nobody could
have known before the season, so it bounds what any constant could have done
rather than standing for one a forecaster might have used. The honest constant
is the last thing knowable before the season: the 2024-25 home-win rate. This
scores both, side by side, on the same 2025-26 games.

**Recomputation only.** The labels come from `holdout.read_holdout_labels`,
which requires the seal's marker, and are refused unless they hash to the value
the marker recorded. `open_holdout` is not imported and cannot be reached from
here. Nothing is fitted: both forecasters are constants.

**The end-of-season re-run is on 2026-27 data, not this script on 2025-26.**
It is the same comparison one season on: 2025-26's home rate as the constant,
scored with the frozen model and Elo on 2026-27's outcomes (TODOS.md). This
script stays fixed to 2025-26, and since those labels are pinned by the marker's
hash and the 2024-25 rate by the snapshot, running it again reproduces these
numbers exactly -- which is what `EXPECTED` checks.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

import numpy as np

from chira.analysis import open_frame
from chira.holdout import (
    DEV_SEASON,
    HOLDOUT_SEASON,
    _digest,
    dev_labels,
    marker_path,
    read_holdout_labels,
)
from chira.scoring import score_set

AS_OF = "2026-10-23"
RERUN = "end of the 2026-27 season, on 2026-27 data"
OUT = "docs/charts/holdout-exante.json"

# What this run must reproduce, to the five decimals it was first quoted with
# (notes/week9-holdout.md; computed 2026-10-23 from the census's 2024-25 NHL
# home rate and the 2025-26 home rate implied by holdout.json's base rate).
EXPECTED = {("nhl", "ex_ante_brier"): 0.25114}
DECIMALS = 5


def home_rate(rows: list[dict], sport: str) -> tuple[float, int]:
    ys = [r["y"] for r in rows if r["sport"] == sport]
    return float(np.mean(ys)), len(ys)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    if not marker_path(".").is_file():
        print("refusing: no seal marker. This script only RECOMPUTES from "
              "labels already released; it never opens the holdout.")
        return 1
    marker = json.loads(marker_path(".").read_text(encoding="utf-8"))

    snap = args.snapshot or sorted(glob.glob("data/snapshots/census-*"))[-1]
    con = open_frame(snap, verify=not args.no_verify)
    labels = read_holdout_labels(con)
    digest = _digest(labels)
    if digest != marker["label_sha256"]:
        print(f"refusing: the labels hash to {digest[:16]}, not the "
              f"{marker['label_sha256'][:16]} the marker recorded")
        return 1
    dev = dev_labels(con)

    report: dict = {
        "as_of": AS_OF, "rerun": RERUN,
        "holdout_season": HOLDOUT_SEASON, "dev_season": DEV_SEASON,
        "marker": {"commit": marker["commit"], "opened_at": marker["opened_at"],
                   "label_sha256": marker["label_sha256"]},
        "snapshot": Path(snap).name,
        "note": ("ex_ante is a constant at the dev season's home-win rate, "
                 "knowable before 2025-26; hindsight is a constant at 2025-26's "
                 "own rate, which holdout.json calls base_rate. Both are scored "
                 "on every 2025-26 game, the sample holdout.json's model and "
                 "base_rate use."),
        "sports": {}}

    print(f"labels: {len(labels):,}, sha256 {digest[:16]} (matches the marker)")
    for sport in ("nba", "nhl"):
        rows = [r for r in labels if r["sport"] == sport]
        y = np.array([r["y"] for r in rows], dtype=float)
        ids = [r["game_id"] for r in rows]
        seasons = [HOLDOUT_SEASON] * len(rows)
        c_dev, n_dev = home_rate(dev, sport)
        c_hold, _ = home_rate(labels, sport)
        out = {"n": len(rows), "dev_home_rate": c_dev, "n_dev": n_dev,
               "holdout_home_rate": c_hold}
        for name, c in (("ex_ante", c_dev), ("hindsight", c_hold)):
            s = score_set(np.full(len(rows), c), y, seasons=seasons,
                          game_ids=ids)
            out[name] = s.__dict__.copy()
        out["ex_ante_brier"] = out["ex_ante"]["brier"]
        out["hindsight_brier"] = out["hindsight"]["brier"]
        report["sports"][sport] = out
        print(f"{sport.upper()}  {DEV_SEASON} home rate {c_dev:.4f} (n={n_dev:,})"
              f"  {HOLDOUT_SEASON} home rate {c_hold:.4f} (n={len(rows):,})")
        print(f"  ex-ante constant   Brier {out['ex_ante_brier']:.5f}")
        print(f"  hindsight constant Brier {out['hindsight_brier']:.5f}")

    tol = 0.5 * 10 ** -DECIMALS
    bad = []
    for (sport, key), want in EXPECTED.items():
        got = report["sports"][sport][key]
        if abs(got - want) > tol + 1e-12:
            bad.append(f"{sport} {key}: {got:.8f}, expected {want:.{DECIMALS}f}")
    if bad:
        print("\nREFUSING TO WRITE: does not reproduce")
        for b in bad:
            print(f"  - {b}")
        return 1

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1, sort_keys=True)
                              + "\n", encoding="utf-8")
    print("\nreproduces: " + ", ".join(f"{s} {k} {v:.{DECIMALS}f}"
                                       for (s, k), v in EXPECTED.items()))
    print(f"wrote {args.out}  (as of {AS_OF}; re-run at the {RERUN})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
