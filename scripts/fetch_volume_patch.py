"""Recover the volume the census missed, into a side table beside the snapshot.

    uv run python scripts/fetch_volume_patch.py

326 priced games carry no `volume`. Week 5 established why, and the two windows
are NOT the same problem:

- **8 NBA games on 2024-11-12/13.** Their moneyline market DOES carry volume,
  under `volumeClob`. `census._volume` tried only `volumeNum` then `volume`, so
  it recorded NULL. Measured on 7 normal games where both exist, `volumeClob`
  equals the stored volume EXACTLY (ratio 1.000), so this recovers the
  pre-registered quantity rather than substituting a different one.
- **318 games between 2026-03-04 and 2026-03-25.** Gamma has no per-market
  volume for these at all, confirmed against `/events?slug=`, `/markets/{id}`
  and `/markets?condition_ids=` (which returns empty). PREREGISTRATION.md
  Amendment 4 withdraws the event-level proxy Amendment 3c had adopted, because
  event volume is present on only ~36% of them and reads $350-$11,169 against
  season medians of $604k and $2.03M. These games are recorded here as
  `volume_source='none'` and are excluded from the liquidity axis as a named,
  counted category.

**Why a side table and not a re-cut snapshot.** The snapshot's store digest is
quoted in README.md, notes/week3-census.md and docs/charts/chart-data.json, and
PREREGISTRATION.md section 1 freezes the volume definition with that hash. A
side table leaves all of that intact and is folded into the dataset release in
week 6.

**Why the cache first.** The frozen definition is volume "as reported by Gamma
at census time". Week 3's `.http-cache` holds those exact responses, so a cache
hit is MORE faithful than a fresh fetch, not less. Live is the fallback.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import duckdb

sys.path.insert(0, "src")
from chira.analysis import open_frame
from chira.cache import Cache
from chira.census import load_abbr_map, map_fingerprint
from chira.constants import GAMMA
from chira.http import Client, validate_events
from chira.telemetry import git_hash

ABBR = "data/abbr_map_resolved.json"
PATCH_FORMAT = 1

# Tried in order. `volumeClob` is the field the census missed; the other two are
# the pre-registered names, kept first so an ordinary game is unaffected.
VOLUME_KEYS = ("volumeNum", "volume", "volumeClob")


def _num(value: object) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def recover(market: dict) -> tuple[float | None, str]:
    for key in VOLUME_KEYS:
        v = _num(market.get(key))
        if v is not None:
            return v, key
    return None, "none"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--out", default="data/volume_patch")
    ap.add_argument("--cache", default=".http-cache")
    ap.add_argument("--live", action="store_true",
                    help="bypass the census cache and refetch (less faithful to "
                         "the frozen definition; for checking drift only)")
    args = ap.parse_args()

    snap = args.snapshot or sorted(glob.glob("data/snapshots/census-*"))[-1]
    con = open_frame(snap, verify=False)
    manifest = json.loads((Path(snap) / "manifest.json").read_text(encoding="utf-8"))
    missing = con.execute("""
        SELECT p.sport, p.season, p.game_id, p.slug, CAST(g.et_date AS VARCHAR)
        FROM priced p JOIN games g USING (sport, season, game_id)
        WHERE p.volume IS NULL
        ORDER BY p.sport, p.season, p.game_id
    """).fetchall()
    print(f"snapshot: {snap}\ngames with no volume: {len(missing)}")

    rows, stats = [], Counter()
    clients: dict[tuple[str, str], Client] = {}
    for sport, season, game_id, slug, et_date in missing:
        key = (sport, season)
        if key not in clients:
            # The cache mixes the abbr-map fingerprint into slug= URLs, so the
            # census's own entries are only reachable with the same map.
            amap = load_abbr_map(ABBR, season, sport)
            clients[key] = Client(cache=Cache(args.cache,
                                              abbr_version=map_fingerprint(amap)))
        client = clients[key]
        before = client.stats["cache:hit"]
        try:
            events = client.get_json(f"{GAMMA}/events?slug={slug}",
                                     validator=validate_events,
                                     bypass_cache=args.live)
        # Broad by intent: one bad game must not end the pass.
        except Exception as e:
            stats[f"error:{type(e).__name__}"] += 1
            rows.append((sport, season, game_id, slug, et_date, None, "error",
                         False, str(e)[:200]))
            continue
        cached = client.stats["cache:hit"] > before
        markets = (events[0].get("markets") or []) if events else []
        moneyline = [m for m in markets if m.get("sportsMarketType") == "moneyline"]
        if not moneyline:
            stats["no_moneyline"] += 1
            rows.append((sport, season, game_id, slug, et_date, None,
                         "no_moneyline", cached, None))
            continue
        volume, source = recover(moneyline[0])
        stats[source] += 1
        stats["cache_hit" if cached else "live"] += 1
        rows.append((sport, season, game_id, slug, et_date, volume, source,
                     cached, None))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    parquet = out / "volume_patch.parquet"
    db = duckdb.connect(":memory:")
    db.execute("""
        CREATE TABLE volume_patch (
            sport TEXT, season TEXT, game_id TEXT, slug TEXT, et_date TEXT,
            volume_recovered DOUBLE, volume_source TEXT,
            from_census_cache BOOLEAN, note TEXT)
    """)
    db.executemany("INSERT INTO volume_patch VALUES (?,?,?,?,?,?,?,?,?)", rows)
    db.execute(f"COPY (SELECT * FROM volume_patch ORDER BY sport, season, game_id) "
               f"TO '{parquet.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")

    digest = hashlib.sha256(parquet.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps({
        "patch_format": PATCH_FORMAT,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_hash": git_hash(),
        "base_snapshot_id": manifest["snapshot_id"],
        "base_store_digest": manifest["store_digest"],
        "rows": len(rows),
        "by_source": dict(stats),
        "volume_keys_tried": list(VOLUME_KEYS),
        "files": {"volume_patch.parquet": digest},
        "definition": (
            "volume_recovered is the moneyline market's terminal cumulative volume "
            "for games where priced.volume is NULL, read from the first present of "
            "volumeNum, volume, volumeClob and recorded in volume_source. "
            "volumeClob was measured equal to the stored volume (ratio 1.000) on 7 "
            "normal games, so this recovers the pre-registered quantity rather than "
            "substituting another. volume_source='none' means Gamma has no "
            "per-market volume at all; those games are excluded from the liquidity "
            "axis per PREREGISTRATION.md Amendment 4 and are NOT proxied."),
    }, indent=2, sort_keys=True), encoding="utf-8")

    print(f"\nby source: {dict(stats)}")
    recovered = sum(1 for r in rows if r[5] is not None)
    print(f"recovered {recovered} of {len(rows)}; {len(rows) - recovered} have no "
          f"per-market volume anywhere and stay out of the liquidity axis")
    print(f"wrote {parquet} ({digest[:12]}) and {out / 'manifest.json'}")
    for c in clients.values():
        print(f"  http: {dict(c.stats)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
