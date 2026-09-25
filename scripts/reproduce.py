"""Reproduce the whole thing, end to end, from public endpoints.

    uv run python scripts/reproduce.py          # print the plan, run nothing
    uv run python scripts/reproduce.py --run    # actually do it

There is no dataset to download (Polymarket's terms define "Data" to include
derived and aggregated forms, so this project publishes code and results, not
data -- see notes/week1-tos-check.md). This script is the replacement: it
rebuilds the census, the snapshot and every published figure from the public
APIs.

**It prints the plan and exits unless you pass --run.** The census is ~16,400
requests over roughly two hours; a script that starts that because someone
typed the wrong thing is a script that wastes an afternoon.

Cross-platform: pure Python, no shell, `sys.executable` rather than a hardcoded
interpreter path, so it runs the same on Windows as on macOS and Linux.
"""
from __future__ import annotations

import argparse
import glob
import shutil
import subprocess
import sys
import time
from pathlib import Path

SPORT_SEASONS = (("nba", "2024-25"), ("nba", "2025-26"),
                 ("nhl", "2024-25"), ("nhl", "2025-26"))

# Roughly 6 GB: 5.1 GB of HTTP cache measured on the real run, a 460 MB store
# and a 162 MB snapshot, plus room for the snapshot's working files.
REQUIRED_FREE_BYTES = 6 * 1024**3


def steps() -> list[dict]:
    """Every stage, in order, with what it needs and what it leaves behind."""
    out = [
        {"name": "abbreviation prior",
         "cmd": ["scripts/learn_abbr.py"],
         "makes": "data/abbr_map.json",
         "why": "learns {slug_abbr: nickname} from Gamma (~180 requests)",
         "network": True},
        {"name": "abbreviation map",
         "cmd": ["scripts/resolve_abbrs.py"],
         "makes": "data/abbr_map_resolved.json",
         "why": "confirms every team-season against the market's own outcomes; "
                "NHL needs 7 translations including vgk->las",
         "network": True},
    ]
    for sport, season in SPORT_SEASONS:
        out.append({
            "name": f"census {sport} {season}",
            "cmd": ["scripts/run_census.py", "--sport", sport, "--season", season],
            "makes": f"data/gate-{sport}-{season}.json",
            "why": "pulls every game's market and price series, then runs the "
                   "7-check validation gate; resumable, so re-running is safe",
            "network": True,
        })
    out += [
        {"name": "snapshot",
         "cmd": ["scripts/make_snapshot.py"],
         "makes": "data/snapshots",
         "why": "freezes the census as immutable checksummed Parquet; every "
                "later step reads this and never the live API",
         "network": False},
        {"name": "volume side table",
         "cmd": ["scripts/fetch_volume_patch.py"],
         "makes": "data/volume_patch/volume_patch.parquet",
         "why": "recovers volume for the 8 games whose market reports it only "
                "as volumeClob, and records the 318 that have none at all",
         "network": True},
        {"name": "charts 1 and 2",
         "cmd": ["scripts/make_charts.py"],
         "makes": "docs/charts/chart-data.json",
         "why": "coverage by week of season, and the market's own calibration",
         "network": False},
        {"name": "headline 2",
         "cmd": ["scripts/run_headline2.py", "--reps", "2000"],
         "makes": "docs/charts/headline2.json",
         "why": "the strata, the primary test and every robustness split; "
                "--reps 2000 is what the published intervals used",
         "network": False},
    ]
    return out


def exists(target: str) -> bool:
    return bool(glob.glob(target)) or Path(target).exists()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true",
                    help="execute the plan instead of printing it")
    ap.add_argument("--from", dest="start", type=int, default=1,
                    help="start at step N (1-based), for resuming")
    ap.add_argument("--skip-done", action="store_true",
                    help="skip steps whose output already exists")
    args = ap.parse_args()

    plan = steps()
    print("Chira, end to end. No dataset download: everything is rebuilt from "
          "public endpoints.\n")
    for i, s in enumerate(plan, 1):
        done = " [output present]" if exists(s["makes"]) else ""
        net = "network" if s["network"] else "offline"
        print(f"  {i:2}. {s['name']:24} ({net}){done}")
        print(f"      {s['why']}")
        print(f"      -> {s['makes']}")
    free = shutil.disk_usage(Path.cwd()).free
    print(f"\nDisk: {free / 1e9:.1f} GB free, about "
          f"{REQUIRED_FREE_BYTES / 1e9:.0f} GB needed.")
    print("Time: roughly 2 hours, almost all of it the census's ~16,400 requests "
          "at 5 rps.")
    print("You need a residential or campus IP: stats.nba.com blocks most cloud "
          "ranges, so the NBA schedule fetch times out from a VM.")

    if not args.run:
        print("\nThis was a dry run. Add --run to execute, or --run --skip-done "
              "to fill in only what is missing.")
        return 0
    if free < REQUIRED_FREE_BYTES:
        print(f"\nREFUSING TO START: {free / 1e9:.1f} GB free is below the "
              f"{REQUIRED_FREE_BYTES / 1e9:.0f} GB budget. Free space first; the "
              f"census dies at request 12,000 otherwise.")
        return 2

    started = time.monotonic()
    for i, s in enumerate(plan, 1):
        if i < args.start:
            print(f"\n[{i}/{len(plan)}] {s['name']}: skipped (--from {args.start})")
            continue
        if args.skip_done and exists(s["makes"]):
            print(f"\n[{i}/{len(plan)}] {s['name']}: skipped, {s['makes']} exists")
            continue
        print(f"\n[{i}/{len(plan)}] {s['name']}")
        cmd = [sys.executable, *s["cmd"]]
        print("      " + " ".join(cmd))
        t0 = time.monotonic()
        result = subprocess.run(cmd, check=False)
        mins = (time.monotonic() - t0) / 60
        if result.returncode != 0:
            print(f"\nFAILED at step {i} ({s['name']}) after {mins:.1f} min, "
                  f"exit {result.returncode}.")
            print(f"Fix it, then resume with: --run --from {i}")
            print("The census writes every completed game to the store as it "
                  "goes, so a resumed run re-fetches nothing it already has.")
            return 1
        print(f"      done in {mins:.1f} min")

    print(f"\nAll {len(plan)} steps done in "
          f"{(time.monotonic() - started) / 60:.1f} min.")
    print("Published figures are in docs/charts/. The writeup that reads them is "
          "docs/index.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
