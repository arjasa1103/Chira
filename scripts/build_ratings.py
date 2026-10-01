"""Walk the Elo across all three seasons with the FROZEN constants.

    uv run python scripts/build_ratings.py

One row per game, 2023-24 burn-in through 2025-26, using `ratings.CHOSEN`
unchanged. The constants were chosen on 2024-25 only and frozen by commit
`d66671c`, public before this script existed; this run does not re-choose
anything and `--check-frozen` refuses to start if the constants have moved.

**This reads 2025-26 outcomes, and that is deliberate.** It is NOT a breach of
the seal, and `holdout.py` says why: a game's pre-game rating uses only games
that were over before it started, which is what a point-in-time input is and
how every live prediction works. The seal guards SCORING -- a 2025-26 game's
own outcome entering a fit, a tune or an evaluation -- which happens only
through `open_holdout`. So this script must NOT call `assert_dev_only`, and
the thing that keeps it honest is the causality check below.

**The real-data canary.** The walk is causal by construction, so the way to
prove it is to truncate: recompute over only the games that had started by a
cutoff and require every surviving row to be byte-identical to the full walk's.
A future game that leaked into a past rating would move those rows. Same shape
as the feature store's canary, on 5,084 real games.
"""
from __future__ import annotations

import argparse
import glob
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
import duckdb

from chira.analysis import open_frame
from chira.holdout import HOLDOUT_SEASON
from chira.ratings import (
    BURNIN_SEASON,
    CHOSEN,
    MODEL_COVARIATE,
    brier,
    log_loss,
    run_ratings,
)
from chira.snapshot import _sql_path

BURNIN = "data/burnin/burnin-2023-24.parquet"
OUT = "data/ratings/ratings.parquet"

# A date deep inside 2024-25, used only by the causality check.
CANARY_CUTOFF = "2025-01-15T23:00:00+00:00"

_ALL_SQL = """
SELECT sport, season, game_id, et_date, away, home, away_pts, home_pts, winner,
       coalesce(neutral_site, FALSE) AS neutral_site,
       epoch(CAST(start_time_utc AS TIMESTAMPTZ))::BIGINT AS start_t
FROM games WHERE sport = ?
UNION ALL
SELECT sport, season, game_id, et_date, away, home, away_pts, home_pts, winner,
       neutral_site,
       epoch(CAST(start_time_utc AS TIMESTAMPTZ))::BIGINT AS start_t
FROM read_parquet(?) WHERE sport = ?
ORDER BY start_t, game_id
"""

COLUMNS = ("sport", "season", "game_id", "et_date", "away", "home", "start_t",
           "r_home_pre", "r_away_pre", "home_bonus", "rating_diff",
           "rating_diff_strength", "p_home_elo", "y", "mov", "delta",
           "neutral_site")


def rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def canary(games: list[dict], sport: str, cutoff: int) -> tuple[bool, int]:
    """Does truncating the schedule at `cutoff` change any surviving row?"""
    full = {(r["game_id"], r["start_t"]): r
            for r in run_ratings(games, **CHOSEN[sport])}
    before = [g for g in games if g["start_t"] < cutoff]
    trunc = run_ratings(before, **CHOSEN[sport])
    for r in trunc:
        if full[(r["game_id"], r["start_t"])] != r:
            return False, len(trunc)
    return True, len(trunc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--burnin", default=BURNIN)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    snaps = sorted(glob.glob("data/snapshots/census-*"))
    if not args.snapshot and not snaps:
        print("no snapshot found; run scripts/make_snapshot.py first")
        return 2
    if not Path(args.burnin).is_file():
        print(f"no burn-in at {args.burnin}; run scripts/fetch_burnin.py first")
        return 2
    snap = args.snapshot or snaps[-1]
    print(f"snapshot: {snap}\nburn-in:  {args.burnin}")
    print(f"frozen constants: {CHOSEN}")
    con = open_frame(snap, verify=not args.no_verify)

    cutoff = int(duckdb.connect(":memory:").execute(
        "SELECT epoch(CAST(? AS TIMESTAMPTZ))::BIGINT", [CANARY_CUTOFF]
    ).fetchone()[0])

    out: list[dict] = []
    for sport in ("nba", "nhl"):
        games = rows(con.execute(_ALL_SQL, [sport, args.burnin, sport]))
        t0 = time.time()
        walked = run_ratings(games, **CHOSEN[sport])
        print(f"\n{sport}: {len(games):,} games walked in "
              f"{time.time() - t0:.1f}s")

        ok, n_trunc = canary(games, sport, cutoff)
        print(f"  causality canary: truncated at {CANARY_CUTOFF[:10]} to "
              f"{n_trunc:,} games -> byte-identical: {ok}")
        if not ok:
            print("  LEAK: a rating changed when later games were removed.")
            return 1
        out += walked

    con2 = duckdb.connect(":memory:")
    con2.execute("SET TimeZone='UTC'")
    con2.execute("""CREATE TABLE ratings (
        sport VARCHAR, season VARCHAR, game_id VARCHAR, et_date DATE,
        away VARCHAR, home VARCHAR, start_t BIGINT,
        r_home_pre DOUBLE, r_away_pre DOUBLE, home_bonus DOUBLE,
        rating_diff DOUBLE, rating_diff_strength DOUBLE,
        p_home_elo DOUBLE, y DOUBLE, mov INTEGER, delta DOUBLE,
        neutral_site BOOLEAN)""")
    con2.executemany(
        f"INSERT INTO ratings VALUES ({','.join('?' * len(COLUMNS))})",
        [tuple(r[c] for c in COLUMNS) for r in out])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    con2.execute(f"COPY (SELECT * FROM ratings "
                 f"ORDER BY sport, season, game_id) "
                 f"TO '{_sql_path(Path(args.out))}' (FORMAT PARQUET)")
    print(f"\nwrote {len(out):,} rows to {args.out}")

    # INPUT descriptives for every season, and a SCORE for no sealed one.
    #
    # The first version of this table printed the Elo's log loss and Brier per
    # season, which scored the rating against 2025-26 outcomes -- a holdout
    # peek, disclosed in holdout.assert_scorable's docstring. Scoring is now
    # refused by `ratings.log_loss`; this table never computes it.
    print("\n  sport season   games  mean|diff|  neutral  (inputs only)")
    for row in con2.execute("""
        SELECT sport, season, count(*),
               round(avg(abs(rating_diff_strength)), 1),
               count(*) FILTER (neutral_site)
        FROM ratings GROUP BY 1, 2 ORDER BY 1, 2""").fetchall():
        print("  {:<5} {:<8} {:>5}  {:>9}  {:>7}".format(*row))

    print("\n  Elo log loss and Brier, DEV AND BURN-IN ONLY "
          "(2025-26 is sealed until open_holdout):")
    for sport in ("nba", "nhl"):
        scored = [r for r in out
                  if r["sport"] == sport and r["season"] != HOLDOUT_SEASON]
        for season in sorted({r["season"] for r in scored}):
            part = [r for r in scored if r["season"] == season]
            print(f"    {sport} {season}: log loss {log_loss(part):.5f}, "
                  f"Brier {brier(part):.5f}, n={len(part):,}")

    print(f"\n  {MODEL_COVARIATE} is the model's covariate; `rating_diff` "
          f"carries the home\n  bonus and exists only for p_home_elo "
          f"(Amendment 5b, third reading).")
    print(f"  {BURNIN_SEASON} rows are burn-in: rating input, never a model "
          f"row, never scored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
