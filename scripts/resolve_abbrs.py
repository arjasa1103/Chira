"""Resolve {schedule_abbr: slug_abbr} per sport per season, from the schedule.

Writes data/abbr_map_resolved.json. This is the map the census actually reads;
data/abbr_map.json (week 1) is only a PRIOR into it.

Run: uv run python scripts/resolve_abbrs.py
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, "src")
from chira.cache import Cache
from chira.constants import USABLE_SEASONS
from chira.http import Client
from chira.nhl import nhl_games
from chira.resolve import invert_learned, resolve
from chira.schedule import nba_games

DATA = pathlib.Path("data")
learned = json.loads((DATA / "abbr_map.json").read_text(encoding="utf-8"))

out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seasons": {}}
# Share the census cache. This script fetches the 64 NHL club-schedule payloads
# (~12 MB) that run_census.py then fetched again -- the only place in the pipeline
# where the same url was provably requested twice in normal operation. Those are
# map-independent keys, so both runs hit the same cache entry. The ~91 slug probes
# ARE keyed by abbr_version and will not be shared with the census; that is
# correct, since the map they are keyed under is the one being derived.
client = Client(cache=Cache(".http-cache", abbr_version="resolver"))

for season in USABLE_SEASONS:
    out["seasons"][season] = {}
    for sport in ("nba", "nhl"):
        t0 = time.time()
        if sport == "nba":
            games = nba_games(season)
        else:
            games = nhl_games(client, season)
        # Priors, best first: this season's learned map, then the other
        # season's (conventions mostly persist across seasons, but not always,
        # which is why this is a prior and not the answer).
        priors = [invert_learned(learned, sport, season)]
        priors += [invert_learned(learned, sport, s)
                   for s in USABLE_SEASONS if s != season]
        r = resolve(client, sport, games, priors, verbose=True)
        r["n_games"] = len(games)
        r["prior_sizes"] = [len(p) for p in priors]
        out["seasons"][season][sport] = r
        print(f"{season} {sport}: {len(r['map'])}/{len(r['map']) + len(r['unresolved'])} teams, "
              f"{r['probes']} probes, {len(games)} games, {time.time() - t0:.0f}s")
        if r["unresolved"]:
            print(f"  UNRESOLVED: {r['unresolved']}")

(DATA / "abbr_map_resolved.json").write_text(
    json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
print("\nwrote data/abbr_map_resolved.json")
print("http stats:", dict(client.stats))
