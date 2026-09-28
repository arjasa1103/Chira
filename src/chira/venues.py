"""Where each team plays, and how far apart those places are.

PLAN.md Phase 3 lists "rest days, back-to-backs, travel distance" as historical
features. Rest and back-to-backs fall straight out of `games`, which is already
in the store. **Travel does not.** Nothing in the census carries a city, an
arena or a coordinate (audited 2026-09-26, zero matches), so this table is the
missing input, and `features.py` is its only consumer.

**Vendored, not fetched**, for the same reason `nhl.NHL_TEAMS` is: a half-failed
fetch silently shortens the table, and a short venue table does not fail -- it
returns NULL travel for the teams it dropped, which reads as "this team never
travels". Sixty-two hand-checked rows that a test pins are safer than a network
call that cannot be re-run identically in 2030.

**Precision, stated honestly.** These are arena-area coordinates rounded to two
decimal places, which is ~1.1 km of latitude. The feature is inter-city flight
distance, where the smallest real pair is Devils-Rangers at 15 km and the
typical pair is 1,000-3,000 km, so a 1 km rounding is four orders of magnitude
below the signal. They are NOT survey-grade arena positions and must not be
reused as such. `tests/test_venues.py` pins ten pairs against published
great-circle distances.

**Great circle, not flown distance.** A team charter flies an air route with a
departure and an approach, so the real distance is a few percent longer and the
real fatigue depends on time zones and departure hour, neither of which this
models. `tz_offset_std` is carried so a later feature can use the time-zone
change, which is the part of travel the fatigue literature actually leans on.
"""

from __future__ import annotations

import math

# Mean Earth radius (IUGG). The choice matters at the 0.1% level and is fixed
# here so a distance computed in week 7 equals one computed in week 11.
EARTH_RADIUS_KM = 6371.0088

# (lat, lon, city, standard-time UTC offset in hours).
#
# The offset is STANDARD time, never the local wall clock in force on a given
# date: three of these places (Phoenix, and the whole of Saskatchewan, which
# this table happens not to reach) do not observe DST, so a date-dependent
# offset would need a tz database lookup per game. Standard offset is the
# stable quantity; a caller that needs the actual local hour should use
# `zoneinfo` and the game's own timestamp.
NBA_VENUES: dict[str, tuple[float, float, str, float]] = {
    "atl": (33.76, -84.40, "Atlanta, GA", -5),
    "bkn": (40.68, -73.98, "Brooklyn, NY", -5),
    "bos": (42.37, -71.06, "Boston, MA", -5),
    "cha": (35.23, -80.84, "Charlotte, NC", -5),
    "chi": (41.88, -87.67, "Chicago, IL", -6),
    "cle": (41.50, -81.69, "Cleveland, OH", -5),
    "dal": (32.79, -96.81, "Dallas, TX", -6),
    "den": (39.75, -105.01, "Denver, CO", -7),
    "det": (42.34, -83.06, "Detroit, MI", -5),
    "gsw": (37.77, -122.39, "San Francisco, CA", -8),
    "hou": (29.75, -95.36, "Houston, TX", -6),
    "ind": (39.76, -86.16, "Indianapolis, IN", -5),
    # Intuit Dome, Inglewood, from 2024-25 on. Crypto.com Arena (lal) is 9 km
    # away, so the distinction is immaterial to travel and is kept for accuracy.
    "lac": (33.94, -118.34, "Inglewood, CA", -8),
    "lal": (34.04, -118.27, "Los Angeles, CA", -8),
    "mem": (35.14, -90.05, "Memphis, TN", -6),
    "mia": (25.78, -80.19, "Miami, FL", -5),
    "mil": (43.04, -87.92, "Milwaukee, WI", -6),
    "min": (44.98, -93.28, "Minneapolis, MN", -6),
    "nop": (29.95, -90.08, "New Orleans, LA", -6),
    "nyk": (40.75, -73.99, "New York, NY", -5),
    "okc": (35.46, -97.52, "Oklahoma City, OK", -6),
    "orl": (28.54, -81.38, "Orlando, FL", -5),
    "phi": (39.90, -75.17, "Philadelphia, PA", -5),
    # Phoenix does not observe DST. See the note above the table.
    "phx": (33.45, -112.07, "Phoenix, AZ", -7),
    "por": (45.53, -122.67, "Portland, OR", -8),
    "sac": (38.58, -121.50, "Sacramento, CA", -8),
    "sas": (29.43, -98.44, "San Antonio, TX", -6),
    "tor": (43.64, -79.38, "Toronto, ON", -5),
    "uta": (40.77, -111.90, "Salt Lake City, UT", -7),
    "was": (38.90, -77.02, "Washington, DC", -5),
}

NHL_VENUES: dict[str, tuple[float, float, str, float]] = {
    "ana": (33.81, -117.88, "Anaheim, CA", -8),
    "bos": (42.37, -71.06, "Boston, MA", -5),
    "buf": (42.87, -78.88, "Buffalo, NY", -5),
    "car": (35.80, -78.72, "Raleigh, NC", -5),
    "cbj": (39.97, -83.01, "Columbus, OH", -5),
    "cgy": (51.04, -114.05, "Calgary, AB", -7),
    "chi": (41.88, -87.67, "Chicago, IL", -6),
    "col": (39.75, -105.01, "Denver, CO", -7),
    "dal": (32.79, -96.81, "Dallas, TX", -6),
    "det": (42.34, -83.06, "Detroit, MI", -5),
    "edm": (53.55, -113.50, "Edmonton, AB", -7),
    "fla": (26.16, -80.33, "Sunrise, FL", -5),
    "lak": (34.04, -118.27, "Los Angeles, CA", -8),
    "min": (44.94, -93.10, "St. Paul, MN", -6),
    "mtl": (45.50, -73.57, "Montreal, QC", -5),
    "njd": (40.73, -74.17, "Newark, NJ", -5),
    "nsh": (36.16, -86.78, "Nashville, TN", -6),
    # UBS Arena, Elmont, from 2021-22 on -- 30 km east of Madison Square Garden.
    "nyi": (40.71, -73.72, "Elmont, NY", -5),
    "nyr": (40.75, -73.99, "New York, NY", -5),
    "ott": (45.30, -75.93, "Ottawa, ON", -5),
    "phi": (39.90, -75.17, "Philadelphia, PA", -5),
    "pit": (40.44, -79.99, "Pittsburgh, PA", -5),
    "sea": (47.62, -122.35, "Seattle, WA", -8),
    "sjs": (37.33, -121.90, "San Jose, CA", -8),
    "stl": (38.63, -90.20, "St. Louis, MO", -6),
    "tbl": (27.95, -82.45, "Tampa, FL", -5),
    "tor": (43.64, -79.38, "Toronto, ON", -5),
    "uta": (40.77, -111.90, "Salt Lake City, UT", -7),
    "van": (49.28, -123.11, "Vancouver, BC", -8),
    "vgk": (36.10, -115.18, "Las Vegas, NV", -8),
    "wpg": (49.89, -97.14, "Winnipeg, MB", -6),
    "wsh": (38.90, -77.02, "Washington, DC", -5),
}

VENUES: dict[str, dict[str, tuple[float, float, str, float]]] = {
    "nba": NBA_VENUES,
    "nhl": NHL_VENUES,
}

# The census's own team counts. A table that drifts short is the failure mode
# this module exists to prevent, so the expected size is stated rather than
# inferred from the table itself.
EXPECTED_TEAMS = {"nba": 30, "nhl": 32}


def venue(sport: str, team: str) -> tuple[float, float, str, float]:
    """Look one team up. Raises rather than returning None.

    A missing venue must not degrade to "no travel": a NULL distance for one
    team would silently become that team's baseline and the coefficient would
    be estimated off the others.
    """
    table = VENUES.get(sport)
    if table is None:
        raise KeyError(f"no venue table for sport {sport!r}")
    try:
        return table[team]
    except KeyError:
        raise KeyError(f"no venue for {sport} team {team!r}; the table has "
                       f"{len(table)} of an expected "
                       f"{EXPECTED_TEAMS.get(sport, '?')}") from None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres.

    The haversine form is used rather than the spherical law of cosines
    because the short pairs here (Rangers-Devils, 15 km) are exactly where the
    cosine form loses precision.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def distance_km(sport: str, team_a: str, team_b: str) -> float:
    """Great-circle kilometres between two teams' home venues."""
    lat1, lon1, _, _ = venue(sport, team_a)
    lat2, lon2, _, _ = venue(sport, team_b)
    return haversine_km(lat1, lon1, lat2, lon2)


def tz_shift_hours(sport: str, team_a: str, team_b: str) -> float:
    """Standard-time offset difference, b minus a. East-to-west is negative."""
    return venue(sport, team_b)[3] - venue(sport, team_a)[3]


def venue_rows() -> list[dict]:
    """Every venue as a flat row, for materialising the table into DuckDB."""
    return [
        {"sport": sport, "team": team, "lat": lat, "lon": lon,
         "city": city, "tz_offset_std": tz}
        for sport, table in sorted(VENUES.items())
        for team, (lat, lon, city, tz) in sorted(table.items())
    ]


# --- NBA neutral-site regular-season games ---------------------------------
#
# The NHL schedule source sets `neutralSite` and the census stores it.
# `schedule.nba_games` reads nba_api's LeagueGameFinder, whose stat rows carry
# no venue at all, so every NBA row in the store says FALSE **by construction,
# not by measurement**. This table is the missing half.
#
# Vendored from `stats.nba.com/stats/scheduleleaguev2` on 2026-09-28, which
# does carry `arenaName`, `arenaCity` and `isNeutral`. It is vendored rather
# than fetched at runtime for the usual reason, plus one specific to it:
#
# **The league's own `isNeutral` is WRONG for 2023-24.** All four of that
# season's genuinely neutral games -- Mexico City, Paris, and both Emirates
# NBA Cup semifinals in Las Vegas -- carry `isNeutral: false`, while the same
# fixtures in 2024-25 and 2025-26 carry `true`. Trusting the flag would
# silently mis-set the Elo home bonus across the whole burn-in season
# (PREREGISTRATION Amendment 5b). These rows were found by comparing
# `arenaCity` against the home team's own city, which is measurable and does
# not depend on the flag. `scripts/fetch_neutral_sites.py` re-runs exactly
# that comparison and diffs it against this table.
#
# (season, game_id) -> (et_date, away, home, venue, why)
NBA_NEUTRAL_SITES: dict[tuple[str, str], tuple[str, str, str, str, str]] = {
    ("2023-24", "0022300172"):
        ("2023-11-09", "atl", "orl", "Arena CDMX, Mexico City", "NBA Mexico City Game"),
    ("2023-24", "0022301229"):
        ("2023-12-07", "ind", "mil", "T-Mobile Arena, Las Vegas",
         "Emirates NBA Cup East Semifinal"),
    ("2023-24", "0022301230"):
        ("2023-12-07", "nop", "lal", "T-Mobile Arena, Las Vegas",
         "Emirates NBA Cup West Semifinal"),
    ("2023-24", "0022300527"): ("2024-01-11", "bkn", "cle", "Accor Arena, Paris", "NBA Paris Game"),
    ("2024-25", "0022400147"):
        ("2024-11-02", "mia", "was", "Arena CDMX, Mexico City", "NBA Mexico City Game"),
    ("2024-25", "0022401229"):
        ("2024-12-14", "atl", "mil", "T-Mobile Arena, Las Vegas",
         "Emirates NBA Cup East Semifinal"),
    ("2024-25", "0022401230"):
        ("2024-12-14", "hou", "okc", "T-Mobile Arena, Las Vegas",
         "Emirates NBA Cup West Semifinal"),
    ("2024-25", "0022400621"):
        ("2025-01-23", "sas", "ind", "Accor Arena, Paris", "NBA Paris Games"),
    ("2024-25", "0022400633"):
        ("2025-01-25", "ind", "sas", "Accor Arena, Paris", "NBA Paris Games"),
    ("2025-26", "0022500147"):
        ("2025-11-01", "dal", "det", "Arena CDMX, Mexico City", "NBA Mexico City Game"),
    ("2025-26", "0022501229"):
        ("2025-12-13", "nyk", "orl", "T-Mobile Arena, Las Vegas",
         "Emirates NBA Cup East Semifinal"),
    ("2025-26", "0022501230"):
        ("2025-12-13", "sas", "okc", "T-Mobile Arena, Las Vegas",
         "Emirates NBA Cup West Semifinal"),
    ("2025-26", "0022500578"):
        ("2026-01-15", "mem", "orl", "Uber Arena, Berlin", "NBA Berlin Game"),
    ("2025-26", "0022500602"):
        ("2026-01-18", "orl", "mem", "The O2 Arena, London", "NBA London Game"),
}

# Home games moved to another venue in the SAME market. **Not neutral**, and
# deliberately kept out of the table above: the Spurs at the Moody Center are
# 120 km from home in front of their own crowd, so zeroing the home advantage
# there would be a worse error than the 120 km of travel it would fix. The
# median NBA trip in the feature store is ~1,000 km, so the travel error is
# immaterial. Recorded so the decision is visible rather than an omission.
#
# One more of the same kind, with no row because it needs none: the Clippers
# played 2023-24 at Crypto.com Arena and moved to the Intuit Dome for 2024-25.
# `NBA_VENUES["lac"]` holds the Intuit Dome, which is right for both census
# seasons and ~9 km off for the 2023-24 rating burn-in, where travel is not
# used at all.
NBA_RELOCATED_HOME: dict[tuple[str, str], tuple[str, str, str, str, str]] = {
    ("2023-24", "0022300965"): ("2024-03-15", "den", "sas", "Moody Center, Austin", ""),
    ("2023-24", "0022300981"): ("2024-03-17", "bkn", "sas", "Moody Center, Austin", ""),
    ("2024-25", "0022400795"): ("2025-02-20", "phx", "sas", "Moody Center, Austin", ""),
    ("2024-25", "0022400802"): ("2025-02-21", "det", "sas", "Moody Center, Austin", ""),
    ("2025-26", "0022500798"): ("2026-02-19", "phx", "sas", "Moody Center, Austin", ""),
    ("2025-26", "0022500815"): ("2026-02-21", "sac", "sas", "Moody Center, Austin", ""),
}


def is_neutral_site(sport: str, season: str, game_id: str) -> bool:
    """Is this game at a neutral venue, per the vendored NBA table?

    NHL games are not covered: the league's own flag is in the store and is
    correct, so this returns False for them and the caller ORs the two.
    """
    if sport != "nba":
        return False
    return (season, str(game_id)) in NBA_NEUTRAL_SITES


def neutral_site_rows() -> list[dict]:
    """The NBA neutral-site table as flat rows, for materialising into DuckDB."""
    return [
        {"sport": "nba", "season": season, "game_id": game_id,
          "et_date": et_date, "away": away, "home": home,
          "venue": venue, "why": why}
        for (season, game_id), (et_date, away, home, venue, why)
        in sorted(NBA_NEUTRAL_SITES.items())
    ]
