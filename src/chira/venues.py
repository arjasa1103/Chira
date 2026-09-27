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
