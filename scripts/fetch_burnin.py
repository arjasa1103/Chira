"""Fetch the 2023-24 results the Elo burn-in needs (PREREGISTRATION 5b).

    uv run python scripts/fetch_burnin.py

**2023-24 is rating burn-in only.** Section 1 excludes it from the project
because its Polymarket markets carried no trading, and that exclusion stands:
no 2023-24 price is read here, these games are never a model row and are never
scored. All this fetch takes is schedule and final scores, from the same
league sources the census uses.

**It lands in `data/burnin/`, outside the census store and the snapshot.**
Amendment 5b says so, and the reason is the snapshot's content-addressed
digest: adding a season to it would invalidate every reference to
`census-20260913-224d6ad985e0`.

**Utah was Arizona.** `nhl.NHL_TEAMS` carries `UTA`, and
`club-schedule-season/UTA/20232024` returns **zero games with no error** --
measured 2026-10-01. The franchise played 2023-24 as Arizona (`ARI`, 82
games). Worse, the count guard would not have caught it: every Arizona game
appears in its opponent's schedule, so the enumeration still totals 1,312 and
only the team CODE is wrong. This script fetches `ARI` and renames it to
`uta`, which is exactly Amendment 5b's "Utah inherits Arizona's
end-of-2023-24 rating before the pull" -- one franchise, one rating, carried
across the rename.

Both fetches must be complete or this stops and names the shortfall.
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, "src")
import duckdb

from chira.cache import Cache
from chira.http import Client
from chira.nhl import NHL_TEAMS, nhl_games
from chira.schedule import nba_games

BURNIN_SEASON = "2023-24"
OUT = "data/burnin/burnin-2023-24.parquet"

# Expected regular-season game counts. Stated rather than inferred: a short
# count is the failure this script exists to make loud.
EXPECTED = {"nba": 1230, "nhl": 1312}

# The 2023-24 NHL franchise list: Utah's row is Arizona's.
NHL_TEAMS_2023_24 = tuple("ARI" if t == "UTA" else t for t in NHL_TEAMS)
RENAME_2023_24 = {"ari": "uta"}

COLUMNS = ("sport", "season", "game_id", "et_date", "away", "home",
           "away_pts", "home_pts", "winner", "neutral_site", "start_time_utc")


def rename(code: str) -> str:
    return RENAME_2023_24.get(code, code)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--cache", default=".http-cache")
    ap.add_argument("--sports", nargs="*", default=["nhl", "nba"])
    args = ap.parse_args()

    rows: list[tuple] = []
    for sport in args.sports:
        t0 = time.time()
        if sport == "nhl":
            # `abbr_version` keys the cache only for slug lookups
            # (`cache.abbr_sensitive`), and club-schedule is addressed by
            # team and season. The literal is a label, not a map version.
            client = Client(cache=Cache(args.cache, abbr_version="burnin"))
            games = nhl_games(client, BURNIN_SEASON, teams=NHL_TEAMS_2023_24,
                              verbose=False)
        elif sport == "nba":
            # stats.nba.com, so a residential or campus IP. Same constraint
            # the census has.
            games = nba_games(BURNIN_SEASON)
        else:
            print(f"unknown sport {sport!r}")
            return 2

        # `nhl_games` only enforces its count when `teams is NHL_TEAMS`, and
        # this call deliberately passes a different tuple, so the guard is
        # skipped and has to be re-stated here.
        want = EXPECTED[sport]
        if len(games) != want:
            print(f"{sport} {BURNIN_SEASON}: enumerated {len(games)} "
                  f"regular-season games, expected {want}. Short by "
                  f"{want - len(games)}. Refusing to write a partial burn-in: "
                  f"a missing game is a rating that never updated.")
            return 1

        seen_codes = set()
        for g in games:
            away, home = rename(g["away"]), rename(g["home"])
            seen_codes |= {away, home}
            rows.append((sport, BURNIN_SEASON, str(g["game_id"]), g["et_date"],
                         away, home, g["away_pts"], g["home_pts"], g["winner"],
                         bool(g.get("neutral_site", False)),
                         g.get("start_time_utc")))
        print(f"{sport} {BURNIN_SEASON}: {len(games):,} games, "
              f"{len(seen_codes)} team codes, {time.time() - t0:.1f}s")
        if "ari" in seen_codes:
            print("  ERROR: 'ari' survived the rename")
            return 1

    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='UTC'")
    con.execute("CREATE TABLE burnin (sport VARCHAR, season VARCHAR, "
                "game_id VARCHAR, et_date DATE, away VARCHAR, home VARCHAR, "
                "away_pts INTEGER, home_pts INTEGER, winner VARCHAR, "
                "neutral_site BOOLEAN, start_time_utc VARCHAR)")
    con.executemany(f"INSERT INTO burnin VALUES ({','.join('?' * len(COLUMNS))})",
                    rows)
    from pathlib import Path

    from chira.snapshot import _sql_path
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT * FROM burnin ORDER BY sport, season, game_id) "
                f"TO '{_sql_path(Path(args.out))}' (FORMAT PARQUET)")
    print(f"\nwrote {len(rows):,} rows to {args.out}")
    for sport, n, lo, hi, neutral in con.execute(
            "SELECT sport, count(*), min(et_date), max(et_date), "
            "count(*) FILTER (neutral_site) FROM burnin GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(f"  {sport}: {n:,} games {lo} .. {hi}, {neutral} neutral-site")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
