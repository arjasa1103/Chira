"""Run the census (or a limited slice of it) and the week-2 validation gate.

    uv run python scripts/run_census.py --sport nba --season 2024-25 --limit 200

Idempotent: re-running skips games already settled in the store, so this is
also the resume command. `--limit` is the gate handle; run 200 games, read the
gate report, and only then spend the remaining ~15,000 requests.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

sys.path.insert(0, "src")
from chira.cache import Cache
from chira.census import (
    load_abbr_map,
    manifest,
    map_fingerprint,
    reprobe_misses,
    run_census,
)
from chira.gate import format_report, run_gate
from chira.http import Client
from chira.nhl import nhl_games
from chira.schedule import nba_games
from chira.store import Store
from chira.telemetry import Telemetry, run_id

ABBR = "data/abbr_map_resolved.json"
MB_PER_GAME = 0.95           # 0.84 cache (measured) + ~0.1 raw series in the store
GAMES_PER_SPORT_SEASON = 1312


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=("nba", "nhl"), required=True)
    ap.add_argument("--season", required=True)
    ap.add_argument("--limit", type=int, default=None,
                    help="census only N unsettled games (the gate slice)")
    ap.add_argument("--strategy", choices=("stride", "head"), default="stride",
                    help="stride spreads the slice across the season; head takes "
                         "the earliest games (which for NHL have no markets at all)")
    ap.add_argument("--store", default="data/census.duckdb")
    ap.add_argument("--cache", default=".http-cache")
    ap.add_argument("--log", default="data/logs/census.jsonl")
    ap.add_argument("--no-reprobe", action="store_true")
    ap.add_argument("--gate-only", action="store_true",
                    help="skip fetching; just re-run the gate on what is stored")
    ap.add_argument("--complete", action="store_true",
                    help="assert the full-pass identity scheduled == priced + misses. "
                         "Set automatically by a full census run; required explicitly "
                         "for --gate-only, which cannot tell a finished census from "
                         "a slice on its own")
    args = ap.parse_args()

    abbr_map = load_abbr_map(ABBR, args.season, args.sport)
    store = Store(args.store)

    if not args.gate_only:
        # Preflight. Measured week 2: 0.84 MB of cache per priced game, and the
        # store's raw series adds roughly 0.1 MB more. Refuse to start rather
        # than die at request 12,000 with a full disk. Margin 2x.
        free = shutil.disk_usage(pathlib.Path(args.store).resolve().parent).free
        need = int(MB_PER_GAME * 1024 * 1024 * GAMES_PER_SPORT_SEASON * 2)
        if free < need:
            print(f"REFUSING TO START: {free / 1e9:.1f} GB free, need about "
                  f"{need / 1e9:.1f} GB for one sport-season with 2x margin")
            return 2

    if not args.gate_only:
        client = Client(cache=Cache(args.cache, abbr_version=map_fingerprint(abbr_map)))
        games = (nba_games(args.season) if args.sport == "nba"
                 else nhl_games(client, args.season))
        rid = run_id(f"census-{args.sport}")
        tel = Telemetry(args.log, rid, manifest(args.sport, args.season, games, abbr_map,
                                                limit=args.limit,
                                                strategy=args.strategy))
        store.start_run(rid, tel.manifest)
        counts = run_census(client, store, tel, args.sport, args.season, games,
                            abbr_map, limit=args.limit, strategy=args.strategy,
                            verbose=True)
        print(f"census: {counts}")
        if not args.no_reprobe:
            rp = reprobe_misses(client, store, tel, args.sport, args.season,
                                games, abbr_map)
            print(f"reprobe: {rp}")
        store.finish_run(rid)
        tel.close(**counts)
        print(f"http: {dict(client.stats)}")
        print(f"cache: {dict(client.cache.stats)}")
        if client.cache.last_error:
            print(f"cache WRITE FAILURES: {client.cache.last_error}")
        print(f"store digest: {store.digest()}")

    # A slice run cannot satisfy the full-pass balance; the gate checks the
    # instant-by-instant invariants instead. See store.assert_reconciled.
    # --gate-only defaults to the partial check because re-checking a stored
    # slice is its whole purpose; pass --complete after a full census.
    require_complete = args.complete or (args.limit is None and not args.gate_only)
    result = run_gate(store, args.sport, args.season,
                      require_complete=require_complete)
    print()
    print(format_report(result))
    out = pathlib.Path(f"data/gate-{args.sport}-{args.season}.json")
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nwrote {out}")
    store.close()
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
