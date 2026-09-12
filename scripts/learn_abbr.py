"""Run the per-season abbreviation learner and write data/abbr_map.json."""
from __future__ import annotations
import json, pathlib, sys
from chira.abbr import learn, TEAM_COUNT, SEASON_SPANS
from chira.http import Client

def main() -> int:
    c = Client()
    out = {}
    for season in SEASON_SPANS:
        print(f"--- {season} ---", flush=True)
        out[season] = learn(c, season)
    dest = pathlib.Path("data"); dest.mkdir(exist_ok=True)
    (dest / "abbr_map.json").write_text(json.dumps(out, indent=2, sort_keys=True))

    print("\n=== COVERAGE ===")
    for season, r in out.items():
        for sport, m in r["sports"].items():
            need = TEAM_COUNT[sport]
            pct = 100 * len(m) / need
            flag = "OK " if len(m) >= need else "GAP"
            print(f"  {flag} {sport} {season}: {len(m):2d}/{need} teams ({pct:.0f}%)  "
                  f"slugs seen {r['slugs_seen']}")
        if r["conflicts"]:
            print(f"      CONFLICTS {season}: {r['conflicts']}")
    print(f"\nrequest stats: {c.stats}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
