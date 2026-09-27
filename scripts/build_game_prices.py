"""Materialise the narrow `game_prices` table beside the snapshot (PLAN.md T15).

    uv run python scripts/build_game_prices.py

One streaming pass over 145.6M raw price points, ~4 seconds, producing ~37k
rows. Everything after this reads the narrow table; nothing in modeling or
scoring touches `price_points` again.

The output lands in `data/game_prices/`, NOT in the snapshot directory: the
snapshot is content-addressed and its digest is quoted in README.md, so adding
a table to it would invalidate every reference to
`census-20260913-224d6ad985e0`.
"""
from __future__ import annotations

import argparse
import glob
import sys
import time

sys.path.insert(0, "src")
from chira.analysis import open_frame
from chira.prices import GAME_PRICES, attach_game_prices, write_game_prices


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None,
                    help="defaults to the newest data/snapshots/census-*")
    ap.add_argument("--out", default=GAME_PRICES)
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the snapshot checksum pass (it reads 162 MB)")
    args = ap.parse_args()

    snaps = sorted(glob.glob("data/snapshots/census-*"))
    if not args.snapshot and not snaps:
        print("no snapshot found; run scripts/make_snapshot.py first")
        return 2
    snap = args.snapshot or snaps[-1]
    print(f"snapshot: {snap}")

    t0 = time.time()
    con = open_frame(snap, verify=not args.no_verify)
    n = write_game_prices(con, args.out)
    print(f"wrote {n:,} rows to {args.out} in {time.time() - t0:.1f}s")

    attach_game_prices(con, args.out)
    print("\nrows per horizon:")
    for horizon, k in con.execute(
            "SELECT horizon, count(*) FROM game_prices "
            "GROUP BY horizon, horizon_secs ORDER BY horizon_secs DESC").fetchall():
        print(f"  {horizon:>5}: {k:,}")

    # The census computed the same four anchors in Python during week 3. If
    # this SQL disagrees with it on even one game, one of them is wrong and
    # the narrow table must not be used until that is settled.
    mismatch = con.execute("""
        SELECT count(*) FROM priced p
        LEFT JOIN (SELECT sport, season, game_id,
                          max(p) FILTER (horizon = 'close') AS p_close
                   FROM game_prices WHERE side = 'home'
                   GROUP BY 1, 2, 3) g USING (sport, season, game_id)
        WHERE p.p_home_close IS DISTINCT FROM g.p_close
    """).fetchone()[0]
    print(f"\nclose disagreements with the census: {mismatch}")
    return 1 if mismatch else 0


if __name__ == "__main__":
    raise SystemExit(main())
