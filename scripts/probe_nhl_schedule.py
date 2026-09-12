"""E10: name and probe an NHL schedule source.

Half the census depends on an NHL schedule the plan never named. Requirements:
  - one row per game with an ET game date (the slug date), away and home
  - an INDEPENDENT winner, for the E1 label-agreement check
  - callable from GitHub Actions (nba_api's stats.nba.com blocks cloud egress,
    so the NHL source must not have the same problem)
"""
import json
import sys

sys.path.insert(0, "src")
from chira.http import Client

NHL = "https://api-web.nhle.com/v1"
c = Client(rate_rps=3.0)


def head(label, obj, n=1200):
    print(f"\n--- {label} ---")
    s = json.dumps(obj, indent=1)[:n]
    print(s)


# 1. full-season club schedule: one call per team gives the whole season
try:
    d = c.get_json(f"{NHL}/club-schedule-season/TOR/20242025")
    games = d.get("games", [])
    print(f"club-schedule-season/TOR/20242025: {len(games)} games")
    reg = [g for g in games if g.get("gameType") == 2]
    print(f"  gameType==2 (regular season): {len(reg)}")
    head("first regular-season game", reg[0] if reg else None)
except Exception as e:
    print(f"club-schedule-season FAILED: {type(e).__name__}: {e}")

# 2. date-based schedule (a week per call)
try:
    d = c.get_json(f"{NHL}/schedule/2025-01-09")
    weeks = d.get("gameWeek", [])
    print(f"\nschedule/2025-01-09: {len(weeks)} days, "
          f"{sum(len(w.get('games', [])) for w in weeks)} games")
    if weeks and weeks[0].get("games"):
        head("day 0 game 0", weeks[0]["games"][0], 1500)
except Exception as e:
    print(f"schedule FAILED: {type(e).__name__}: {e}")

# 3. does a finished game carry the score AND a clear winner?
try:
    d = c.get_json(f"{NHL}/score/2025-01-09")
    gs = d.get("games", [])
    print(f"\nscore/2025-01-09: {len(gs)} games")
    if gs:
        head("score game 0", gs[0], 1500)
except Exception as e:
    print(f"score FAILED: {type(e).__name__}: {e}")
