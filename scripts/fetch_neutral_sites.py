"""Re-derive the NBA neutral-site table and diff it against the vendored copy.

    uv run python scripts/fetch_neutral_sites.py

`venues.NBA_NEUTRAL_SITES` is vendored, for the same reason `nhl.NHL_TEAMS`
is: a half-failed fetch silently SHORTENS the table, and a short neutral-site
table does not fail -- it scores a game in Paris as an ordinary home game.
This script is how the vendored copy stays checkable: it re-runs the exact
derivation and exits non-zero on any disagreement.

**It does not trust the league's `isNeutral` field, and that is deliberate.**
Measured 2026-09-28: all four genuinely neutral 2023-24 games (Mexico City,
Paris, and both Emirates NBA Cup semifinals in Las Vegas) carry
`isNeutral: false`, while the identical fixtures in 2024-25 and 2025-26 carry
`true`. The derivation used here compares `arenaCity` against the home team's
own city, which is measurable and does not depend on the flag. The flag is
fetched anyway and reported where it disagrees.

Network: stats.nba.com, three requests. Needs a residential or campus IP --
stats.nba.com blocks most cloud ranges, the same constraint the census has.
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, "src")
from chira.venues import NBA_NEUTRAL_SITES, NBA_RELOCATED_HOME, NBA_VENUES

# The season the Elo burn-in needs (Amendment 5b) plus the two census seasons.
SEASONS = ("2023-24", "2024-25", "2025-26")
REGULAR_SEASON_PREFIX = "002"

# The NBA writes some cities differently from `venues.py`, which stores the
# arena's town. Only the disagreements are listed.
CITY_ALIAS = {"gsw": "San Francisco", "bkn": "Brooklyn", "nyk": "New York",
              "min": "Minneapolis", "uta": "Salt Lake City",
              "was": "Washington", "ind": "Indianapolis"}
# The Clippers played 2023-24 at Crypto.com Arena and moved to the Intuit Dome
# for 2024-25. `NBA_VENUES["lac"]` holds the Intuit Dome.
LAC_CITY_BY_SEASON = {"2023-24": "Los Angeles"}

# Games at a venue in the home team's OWN market: a relocated home game, not a
# neutral site. Keyed by the arena's city.
SAME_MARKET = {("sas", "Austin")}


def home_city(team: str, season: str) -> str:
    if team == "lac" and season in LAC_CITY_BY_SEASON:
        return LAC_CITY_BY_SEASON[season]
    if team in CITY_ALIAS:
        return CITY_ALIAS[team]
    return NBA_VENUES[team][2].split(",")[0]


def derive(season: str) -> tuple[dict, dict, int]:
    """(neutral, relocated, regular-season game count) for one season."""
    from nba_api.stats.endpoints import scheduleleaguev2

    payload = scheduleleaguev2.ScheduleLeagueV2(
        season=season, league_id="00").get_dict()
    neutral, relocated, n = {}, {}, 0
    for day in payload["leagueSchedule"]["gameDates"]:
        for g in day["games"]:
            gid = str(g.get("gameId", ""))
            if not gid.startswith(REGULAR_SEASON_PREFIX):
                continue
            n += 1
            home = (g.get("homeTeam") or {}).get("teamTricode", "").lower()
            away = (g.get("awayTeam") or {}).get("teamTricode", "").lower()
            city = (g.get("arenaCity") or "").strip()
            if not city or city == home_city(home, season):
                continue
            why = " ".join(x for x in (g.get("gameLabel"),
                                       g.get("gameSubLabel")) if x).strip()
            row = (g["gameDateEst"][:10], away, home,
                   f"{g.get('arenaName')}, {city}", why)
            bucket = relocated if (home, city) in SAME_MARKET else neutral
            bucket[(season, gid)] = row
    return neutral, relocated, n


def diff(label: str, got: dict, want: dict) -> int:
    missing = sorted(set(got) - set(want))
    extra = sorted(set(want) - set(got))
    changed = sorted(k for k in set(got) & set(want) if got[k] != want[k])
    for key in missing:
        print(f"  MISSING from {label}: {key} {got[key]}")
    for key in extra:
        print(f"  NOT FOUND upstream, still in {label}: {key} {want[key]}")
    for key in changed:
        print(f"  CHANGED {key}\n      vendored {want[key]}\n      upstream {got[key]}")
    return len(missing) + len(extra) + len(changed)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="*", default=list(SEASONS))
    args = ap.parse_args()

    all_neutral, all_relocated = {}, {}
    for season in args.seasons:
        neutral, relocated, n = derive(season)
        all_neutral.update(neutral)
        all_relocated.update(relocated)
        print(f"{season}: {n:,} regular-season games, {len(neutral)} neutral, "
              f"{len(relocated)} relocated home")
        for (_, gid), row in sorted(neutral.items()):
            print(f"   neutral    {gid} {row[0]} {row[1]}@{row[2]} "
                  f"{row[3]}  [{row[4]}]")
        for (_, gid), row in sorted(relocated.items()):
            print(f"   relocated  {gid} {row[0]} {row[1]}@{row[2]} {row[3]}")
        time.sleep(1)

    scope = set(args.seasons)
    print("\n=== DIFF AGAINST THE VENDORED TABLES ===")
    bad = diff("NBA_NEUTRAL_SITES", all_neutral,
               {k: v for k, v in NBA_NEUTRAL_SITES.items() if k[0] in scope})
    bad += diff("NBA_RELOCATED_HOME", all_relocated,
                {k: v for k, v in NBA_RELOCATED_HOME.items() if k[0] in scope})
    if bad:
        print(f"\n{bad} disagreement(s). The vendored table in "
              f"src/chira/venues.py needs updating, and anything already fitted "
              f"against the old one is stale.")
        return 1
    print("  no disagreements")

    print("\n=== THE LEAGUE'S OWN isNeutral FLAG ===")
    print("  (not used in the derivation above; reported because it is wrong)")
    stale = sum(1 for season, _ in all_neutral if season == "2023-24")
    print(f"  {stale} neutral 2023-24 game(s), all of which upstream marks "
          f"isNeutral=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
