"""Cut the immutable census snapshot (T7) and verify it by reading it back.

    .venv/bin/python scripts/make_snapshot.py

Refuses unless every sport-season in the store satisfies
`scheduled == priced + misses` and every priced game carries its raw series.
Writes to data/snapshots/<census-YYYYMMDD-digest>/, which is gitignored pending
the Polymarket ToS question (E18): this is the local immutable input for weeks
4+, not the public dataset release (T11).
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "src")
from chira.snapshot import SnapshotError, create_snapshot, open_snapshot
from chira.store import Store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/census.duckdb")
    ap.add_argument("--out", default="data/snapshots")
    args = ap.parse_args()

    with Store(args.store) as store:
        try:
            path = create_snapshot(store, args.out)
        except SnapshotError as e:
            print(f"REFUSED: {e}")
            return 1
        digest = store.digest()

    con = open_snapshot(path)  # verifies every checksum first
    print(f"snapshot: {path}")
    print(f"store digest: {digest}")
    for table in ("games", "priced", "misses", "price_points"):
        rows = con.execute(
            f"SELECT sport, season, count(*) FROM {table} GROUP BY ALL ORDER BY ALL"
        ).fetchall()
        print(f"  {table:13} " + "  ".join(f"{s}/{se}={n:,}" for s, se, n in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
