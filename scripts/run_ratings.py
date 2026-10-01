"""Tune the Elo rating on 2024-25 and freeze it (PREREGISTRATION 5b).

    uv run python scripts/fetch_burnin.py      # once, 2023-24 results
    uv run python scripts/run_ratings.py

**Order matters and git history is the proof of it.** This script chooses K,
the home bonus H and the season carry-over c by lowest log loss over every
2024-25 game. Those three numbers are then written into `ratings.CHOSEN` and
committed BEFORE any 2025-26 rating is computed. Running this after the
freeze reproduces the same grid; it does not re-choose.

**2025-26 is never read here.** The criterion set goes through
`holdout.assert_dev_only`, which refuses the holdout season and refuses rows
with no season at all.

Offline: the snapshot plus `data/burnin/burnin-2023-24.parquet`.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from chira.analysis import open_frame
from chira.holdout import DEV_SEASON, assert_dev_only
from chira.ratings import (
    BURNIN_SEASON,
    GRID,
    GRID_SIZE,
    brier,
    grid_search,
    is_neutral,
    log_loss,
    on_grid_edge,
)

BURNIN = "data/burnin/burnin-2023-24.parquet"
OUT_DIR = "data/ratings"

_GAMES_SQL = """
SELECT sport, season, game_id, et_date, away, home,
       away_pts, home_pts, winner,
       coalesce(neutral_site, FALSE) AS neutral_site,
       epoch(CAST(start_time_utc AS TIMESTAMPTZ))::BIGINT AS start_t
FROM games
WHERE season = ? AND sport = ?
ORDER BY start_t, game_id
"""

_BURNIN_SQL = """
SELECT sport, season, game_id, et_date, away, home,
       away_pts, home_pts, winner, neutral_site,
       epoch(CAST(start_time_utc AS TIMESTAMPTZ))::BIGINT AS start_t
FROM read_parquet(?)
WHERE sport = ?
ORDER BY start_t, game_id
"""


def rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def report_neutral_override(games: list[dict]) -> int:
    """How many games the vendored NBA table makes neutral that the league's
    flag does not. Reporting only: the override itself is applied inside
    `ratings.run_ratings` (`ratings.is_neutral`), so every walk gets it."""
    n = sum(1 for g in games if is_neutral(g) and not g["neutral_site"])
    if n:
        print(f"    neutral-site override applies to {n} game(s)")
    return n


def load_games(con, burnin: str, sport: str) -> tuple[list[dict], list[dict]]:
    """The burn-in and criterion games for one sport, as the grid sees them.

    Both sets pass `holdout.assert_dev_only` here, so the guard sits on the
    loader itself and not on one caller of it.
    """
    burn = rows(con.execute(_BURNIN_SQL, [burnin, sport]))
    dev = rows(con.execute(_GAMES_SQL, [DEV_SEASON, sport]))
    assert_dev_only(dev, what=f"{sport} criterion games")
    assert_dev_only(burn, what=f"{sport} burn-in games")
    return burn, dev


def baselines(games: list[dict]) -> dict:
    """What the grid has to beat to mean anything."""
    y = [1.0 if g["winner"] == "home" else 0.0 for g in games]
    base = sum(y) / len(y)
    half = [{"p_home_elo": 0.5, "y": v} for v in y]
    rate = [{"p_home_elo": base, "y": v} for v in y]
    return {"home_rate": base,
            "log_loss_coinflip": log_loss(half),
            "log_loss_home_rate": log_loss(rate),
            "brier_coinflip": brier(half),
            "brier_home_rate": brier(rate)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--burnin", default=BURNIN)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--sports", nargs="*", default=["nba", "nhl"])
    args = ap.parse_args()

    snaps = sorted(glob.glob("data/snapshots/census-*"))
    if not args.snapshot and not snaps:
        print("no snapshot found; run scripts/make_snapshot.py first")
        return 2
    snap = args.snapshot or snaps[-1]
    if not Path(args.burnin).is_file():
        print(f"no burn-in at {args.burnin}; run scripts/fetch_burnin.py first")
        return 2
    print(f"snapshot: {snap}\nburn-in:  {args.burnin}")
    con = open_frame(snap, verify=not args.no_verify)

    Path(args.out).mkdir(parents=True, exist_ok=True)
    summary = {}
    for sport in args.sports:
        print(f"\n=== {sport.upper()} "
              f"({GRID_SIZE[sport]} grid points) ===")
        burn, dev = load_games(con, args.burnin, sport)
        report_neutral_override(burn + dev)
        print(f"  burn-in {BURNIN_SEASON}: {len(burn):,} games"
              f" | criterion {DEV_SEASON}: {len(dev):,} games")

        base = baselines(dev)
        print(f"  baselines on {DEV_SEASON}: home rate {base['home_rate']:.4f}, "
              f"log loss coinflip {base['log_loss_coinflip']:.5f}, "
              f"home-rate {base['log_loss_home_rate']:.5f}")

        t0 = time.time()
        scored = grid_search(burn + dev, sport, criterion_season=DEV_SEASON)
        best = scored[0]
        edges = on_grid_edge(best, sport)
        print(f"  searched {len(scored)} points in {time.time() - t0:.1f}s")
        print(f"\n  BEST: K={best['k']} H={best['h']} c={best['c']} "
              f"-> log loss {best['log_loss']:.5f}, Brier {best['brier']:.5f} "
              f"on n={best['n']:,}")
        print(f"  improvement over the home-rate baseline: "
              f"{base['log_loss_home_rate'] - best['log_loss']:+.5f} log loss")
        if edges:
            print(f"  LIMITATION: the optimum is on the grid edge in "
                  f"{', '.join(e.upper() for e in edges)}. Reported, not "
                  f"widened (Amendment 5b).")
        else:
            print("  the optimum is interior on all three parameters")

        print("\n  top 10:")
        print("     K    H     c   log loss     Brier")
        for r in scored[:10]:
            print(f"    {r['k']:>2}  {r['h']:>3}  {r['c']:>4}   "
                  f"{r['log_loss']:.5f}   {r['brier']:.5f}")
        spread = scored[-1]["log_loss"] - best["log_loss"]
        print(f"\n  worst point: K={scored[-1]['k']} H={scored[-1]['h']} "
              f"c={scored[-1]['c']} -> {scored[-1]['log_loss']:.5f} "
              f"(spread {spread:.5f})")

        with open(f"{args.out}/grid-{sport}.json", "w", encoding="utf-8") as f:
            json.dump({"sport": sport, "grid": GRID[sport],
                       "criterion_season": DEV_SEASON,
                       "burnin_season": BURNIN_SEASON,
                       "baselines": base, "best": best,
                       "best_on_grid_edge": edges, "points": scored},
                      f, indent=1, sort_keys=True)
        summary[sport] = {"best": best, "edges": edges, "baselines": base}

    print(f"\nwrote {args.out}/grid-*.json")
    print("\nNEXT, in this order (Amendment 5b):")
    print("  1. Put the chosen K/H/c into ratings.CHOSEN and commit, with the")
    print("     full grid in notes/week8-ratings.md, before any 2025-26")
    print("     rating is computed. Git history is the proof of order.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
