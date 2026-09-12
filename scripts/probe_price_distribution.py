"""Week 1: measure the empirical closing-price distribution + run E1 early.

Feeds the noise-floor simulation with a real price distribution instead of an
assumed one, and exercises the whole orientation chain on live data.
"""
from __future__ import annotations

import json
import pathlib
import random
import sys
from collections import Counter

from chira.extract import closing_price, label_agreement
from chira.http import Client
from chira.schedule import nba_games, slug_candidates

N = 130

def main() -> int:
    c = Client()
    rows, tally = [], Counter()
    random.seed(23)
    pool = []
    for season in ("2024-25", "2025-26"):
        g = nba_games(season)
        random.shuffle(g)
        pool += [(season, x) for x in g[: N // 2]]
    print(f"probing {len(pool)} games across both seasons...", flush=True)
    for i, (season, g) in enumerate(pool):
        mkt = None
        conv = None
        for label, s in slug_candidates("nba", g):
            ev = c.event_by_slug(s)
            if ev and (ev[0].get("markets") or []):
                mkt, conv = ev[0]["markets"][0], label
                break
        if mkt is None:
            tally["no_market"] += 1
            continue
        r = closing_price(c, mkt)
        if not r["ok"]:
            tally[f"extract_fail:{r['reason']}"] += 1
            continue
        agree = label_agreement(r.get("market_winner"), g["winner"])
        tally[f"label:{agree}"] += 1
        tally[f"conv:{conv}"] += 1
        if r.get("complement_ok") is False:
            tally["complement_violation"] += 1
        if r.get("stale_flat_run"):
            tally["stale_flat_run"] += 1
        rows.append({"season": season, "game_id": g["game_id"], "et_date": g["et_date"],
                     "p_home_close": r["p_home_close"], "p_home_t1h": r.get("p_home_t1h"),
                     "home_won": 1 if g["winner"] == "home" else 0,
                     "n_pre_tipoff": r["n_pre_tipoff"], "conv": conv,
                     "stale": bool(r.get("stale_flat_run"))})
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(pool)} ... {dict(tally)}", flush=True)
    d = pathlib.Path("data")
    d.mkdir(exist_ok=True)
    (d / "price_sample.json").write_text(json.dumps(rows, indent=2))
    print(f"\n=== {len(rows)} games extracted ===")
    for k, v in sorted(tally.items()):
        print(f"  {k:34} {v}")
    print(f"\nrequest stats: {c.stats}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
