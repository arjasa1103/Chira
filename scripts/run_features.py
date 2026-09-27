"""Build the point-in-time feature store, and run the leakage canary on it.

    uv run python scripts/run_features.py

Three things happen here, in this order, because the third is worthless
without the second:

1. The narrow `game_prices` table is attached (build it first with
   `scripts/build_game_prices.py`). It is NOT joined into the feature frame --
   headline 1 is a price-free model -- it is attached so this script can
   report that the point-in-time price read works.
2. **The leakage canary runs against the real census**, not against a fake.
   PLAN.md Phase 3 pre-registers it: a query with `as_of=T` must return
   byte-identical results against a store truncated at T and a store holding
   every later row. `tests/test_features.py` runs the synthetic version, which
   is where the sharp cases live; this is the version that runs on 5,084 real
   games, where the schedule is messy.
3. The frame is assembled for every game and written to `data/features/`.

Exit codes: 0 all checks passed, 1 a check failed.
"""
from __future__ import annotations

import argparse
import glob
import sys
import time
from datetime import UTC, datetime

sys.path.insert(0, "src")
import duckdb

from chira.analysis import open_frame
from chira.features import (
    FEATURES_PARQUET,
    assemble,
    attach_venues,
    write_backtest,
)
from chira.prices import GAME_PRICES, attach_game_prices, price_as_of

# A date deep inside both leagues' 2024-25 regular season, so the canary runs
# where every team already has a history and the schedule is dense.
CANARY_DATE = "2025-01-15"
CANARY_LOOKAHEAD_HOURS = 48


def truncated_store(con, as_of: int):
    """A second store holding only the games that had STARTED by `as_of`.

    The canary's whole content is that this store and the full one produce
    the same features. Built as a real copy rather than a filtered view so
    the query under test cannot see the later rows at all.
    """
    out = duckdb.connect(":memory:")
    out.execute("SET TimeZone='UTC'")
    rows = con.execute("""
        SELECT sport, season, game_id, et_date, away, home, winner,
               coalesce(neutral_site, FALSE), start_time_utc
        FROM games
        WHERE epoch(CAST(start_time_utc AS TIMESTAMPTZ)) < ?
        ORDER BY sport, season, game_id
    """, [as_of]).fetchall()
    out.execute("""CREATE TABLE games (sport VARCHAR, season VARCHAR,
                   game_id VARCHAR, et_date DATE, away VARCHAR, home VARCHAR,
                   winner VARCHAR, neutral_site BOOLEAN,
                   start_time_utc VARCHAR)""")
    out.executemany("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?)", rows)
    attach_venues(out)
    return out, len(rows)


def canary(con, as_of: int) -> tuple[bool, int, int]:
    """Assemble the next slate twice and compare. Returns (ok, targets, kept)."""
    targets = [
        {"sport": r[0], "season": r[1], "game_id": r[2], "et_date": r[3],
         "away": r[4], "home": r[5], "neutral_site": r[6]}
        for r in con.execute("""
            SELECT sport, season, game_id, et_date, away, home,
                   coalesce(neutral_site, FALSE)
            FROM games
            WHERE epoch(CAST(start_time_utc AS TIMESTAMPTZ)) >= ?
              AND epoch(CAST(start_time_utc AS TIMESTAMPTZ)) < ?
            ORDER BY sport, season, game_id
        """, [as_of, as_of + CANARY_LOOKAHEAD_HOURS * 3600]).fetchall()]
    small, kept = truncated_store(con, as_of)
    full_rows = assemble(con, targets, as_of=as_of)
    small_rows = assemble(small, targets, as_of=as_of)
    return full_rows == small_rows, len(targets), kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--prices", default=GAME_PRICES)
    ap.add_argument("--out", default=FEATURES_PARQUET)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    snaps = sorted(glob.glob("data/snapshots/census-*"))
    if not args.snapshot and not snaps:
        print("no snapshot found; run scripts/make_snapshot.py first")
        return 2
    snap = args.snapshot or snaps[-1]
    print(f"snapshot: {snap}")
    con = open_frame(snap, verify=not args.no_verify)
    n_prices = attach_game_prices(con, args.prices)
    print(f"game_prices: {n_prices:,} rows"
          + ("" if n_prices else "  (run scripts/build_game_prices.py)"))

    as_of = int(datetime.fromisoformat(f"{CANARY_DATE}T23:00:00+00:00")
                .astimezone(UTC).timestamp())
    print(f"\n=== LEAKAGE CANARY (as_of {CANARY_DATE}T23:00Z) ===")
    t0 = time.time()
    ok, n_targets, kept = canary(con, as_of)
    print(f"  targets in the next {CANARY_LOOKAHEAD_HOURS}h: {n_targets}")
    print(f"  games visible in the truncated store: {kept:,} of "
          f"{con.execute('SELECT count(*) FROM games').fetchone()[0]:,}")
    print(f"  byte-identical: {ok}   ({time.time() - t0:.1f}s)")
    if not ok:
        print("  LEAK: the feature frame changed when later rows were "
              "removed. Something in the assembly reads past as_of.")
        return 1

    if n_prices:
        got = price_as_of(con, as_of)
        seen = sum(1 for r in got if r["horizon"] is not None)
        print("\n=== POINT-IN-TIME PRICE READ ===")
        print(f"  games with an anchor visible at as_of: {seen:,} of {len(got):,}")
        future = con.execute(
            "SELECT count(*) FROM game_prices WHERE quote_t > ?", [as_of]
        ).fetchone()[0]
        print(f"  anchors in the store that are still in the future: "
              f"{future:,} (none of them may appear above)")

    print("\n=== FEATURE FRAME ===")
    t0 = time.time()
    n = write_backtest(con, args.out)
    print(f"  {n:,} rows -> {args.out}  ({time.time() - t0:.1f}s)")

    con.execute(f"CREATE OR REPLACE VIEW f AS SELECT * FROM "
                f"read_parquet('{args.out}')")
    print("\n  sport season   games  away_b2b  home_b2b  med_travel_km  "
          "no_venue  first_game")
    for row in con.execute("""
        SELECT sport, season, count(*),
               round(100.0 * avg(CASE WHEN away_b2b THEN 1 ELSE 0 END), 1),
               round(100.0 * avg(CASE WHEN home_b2b THEN 1 ELSE 0 END), 1),
               round(median(away_travel_km)),
               count(*) FILTER (NOT away_travel_known AND NOT away_first_of_season)
                 + count(*) FILTER (NOT home_travel_known AND NOT home_first_of_season),
               count(*) FILTER (away_first_of_season)
                 + count(*) FILTER (home_first_of_season)
        FROM f GROUP BY 1, 2 ORDER BY 1, 2""").fetchall():
        print("  {:<5} {:<8} {:>5}  {:>7}%  {:>7}%  {:>13}  {:>8}  {:>10}"
              .format(*row))

    unsettled = con.execute(
        "SELECT count(*) FROM f WHERE away_prior_games <> away_prior_settled "
        "OR home_prior_games <> home_prior_settled").fetchone()[0]
    print(f"\n  games where a prior result was not yet public at tipoff: "
          f"{unsettled}")
    print("  (zero is expected in the BACKTEST -- a team's previous game is a "
          "day earlier.\n   The availability delay binds for the forward "
          "collector, not here.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
