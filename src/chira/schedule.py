"""Schedule access, and slug construction from it.

Two hard-won rules encoded here:

1. **The ET date comes from the schedule field, never derived from gameStartTime.**
   nba_api's GAME_DATE is already the US-Eastern local game date, which is exactly
   what the slug uses. Deriving ET from a UTC timestamp with a fixed offset breaks
   across DST; deriving it with the right zone works but is needless when the
   schedule hands it to you.

2. **Enumerate from the schedule, never by paginating Gamma.** /markets silently
   caps limit at 100 and returns nothing past offset ~2100, so pagination cannot
   enumerate a season. The week-1 abbreviation learner hit exactly this and
   returned 0/30 NBA teams for 2025-26 while finding 32/32 NHL from identical
   windows.
"""

from __future__ import annotations

import re

MATCHUP_AWAY = re.compile(r"^([A-Z]{3})\s+@\s+([A-Z]{3})$")      # away @ home
MATCHUP_HOME = re.compile(r"^([A-Z]{3})\s+vs\.\s+([A-Z]{3})$")   # home vs. away


def games_from_rows(rows, nick: dict[str, str], place: dict[str, str]) -> list[dict]:
    """Fold per-team stat rows into one row per game. Pure; no network.

    Extracted from `nba_games` so the parts that can be silently wrong are
    testable: MATCHUP orientation, side attribution, and the sort. Each input
    row needs GAME_ID, GAME_DATE, MATCHUP, TEAM_ABBREVIATION, PTS, WL.
    """
    by_game: dict[str, dict] = {}
    for row in rows:
        m = MATCHUP_AWAY.match(row.MATCHUP) or MATCHUP_HOME.match(row.MATCHUP)
        if not m:
            continue
        if "@" in row.MATCHUP:
            away, home = m.group(1), m.group(2)
        else:
            home, away = m.group(1), m.group(2)
        g = by_game.setdefault(row.GAME_ID, {
            "game_id": row.GAME_ID,
            "et_date": str(row.GAME_DATE)[:10],
            "away": away.lower(),
            "home": home.lower(),
            "away_name": nick.get(away.lower(), ""),
            "home_name": nick.get(home.lower(), ""),
            "away_place": place.get(away.lower(), ""),
            "home_place": place.get(home.lower(), ""),
        })
        # PTS/WL arrive per team row; attribute by which side this row is.
        # Defaulting a non-match to "home" silently wrote BOTH rows into the home
        # slot, left away_pts None, and the game was then dropped by the filter
        # below as if it had no data. An abbreviation disagreement must be loud:
        # this is the E1 ground-truth label.
        abbr = row.TEAM_ABBREVIATION.lower()
        if abbr == g["away"]:
            side = "away"
        elif abbr == g["home"]:
            side = "home"
        else:
            raise ValueError(
                f"game {row.GAME_ID}: TEAM_ABBREVIATION {abbr!r} matches neither "
                f"away {g['away']!r} nor home {g['home']!r} from MATCHUP "
                f"{row.MATCHUP!r}"
            )
        g[f"{side}_pts"] = int(row.PTS) if row.PTS is not None else None
        if row.WL == "W":
            g["winner"] = side
    # Keep only games where both team rows were present and a winner resolved,
    # and SORT. LeagueGameFinder returns newest first, so the unsorted order
    # made `--limit 200` census the LAST 200 games of the season while the flag
    # claimed to take the earliest. Sorted output also makes resumption and the
    # stride slice reproducible, and matches nhl.nhl_games.
    return sorted(
        (g for g in by_game.values()
         if g.get("winner") and g.get("away_pts") is not None
         and g.get("home_pts") is not None),
        key=lambda g: (g["et_date"], g["game_id"]),
    )


def nba_team_labels() -> tuple[dict[str, str], dict[str, str]]:
    """({abbr: nickname}, {abbr: city}) from nba_api's OFFLINE static table.

    Not from the game rows, which carry only full names like "Los Angeles
    Lakers". The abbreviation resolver joins on these, so they have to be exact.
    """
    from nba_api.stats.static import teams as static_teams

    static = static_teams.get_teams()
    return ({t["abbreviation"].lower(): t["nickname"] for t in static},
            {t["abbreviation"].lower(): t["city"] for t in static})


def nba_games(season: str, *, timeout: int = 60) -> list[dict]:
    """One row per GAME, with away/home resolved and the independent winner.

    Returns dicts: game_id, et_date, away, home, away_name, home_name,
    away_place, home_place, winner ('away'|'home'), away_pts, home_pts,
    start_time_utc (the league's own tipoff; see attach_start_times).

    The winner field is the E1 label-agreement source: it is independent of
    Polymarket, which is the whole point.
    """
    from nba_api.stats.endpoints import leaguegamefinder, scheduleleaguev2

    nick, place = nba_team_labels()
    df = leaguegamefinder.LeagueGameFinder(
        season_nullable=season,
        season_type_nullable="Regular Season",
        league_id_nullable="00",
        timeout=timeout,
    ).get_data_frames()[0]
    games = games_from_rows(df.itertuples(index=False), nick, place)
    sched = scheduleleaguev2.ScheduleLeagueV2(
        season=season, league_id="00", timeout=timeout).get_data_frames()[0]
    return attach_start_times(
        games, {str(r.gameId): r.gameDateTimeUTC for r in sched.itertuples(index=False)})


def attach_start_times(games: list[dict], league_times: dict[str, object]) -> list[dict]:
    """Add the league's UTC tipoff as `start_time_utc`. Pure; no network.

    A game with no league time gets None, and the census then falls back to
    Gamma's gameStartTime plus the ET-hour plausibility band, recording
    cutoff_source='gamma' on the row so the fallback is countable, never silent.
    Measured: Gamma's time disagreed with this source by more than 15 minutes on
    21 priced NBA games across both seasons, up to 6 hours LATE.
    """
    out = []
    for g in games:
        t = league_times.get(g["game_id"])
        t = str(t) if t is not None and str(t).strip() not in ("", "nan", "None") else None
        out.append(dict(g, start_time_utc=t))
    return out


def slug_candidates(sport: str, game: dict,
                    abbr_map: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Return [(convention, slug)] to try in order.

    TWO candidates, not one. The slug date is usually the ET game date but a
    contaminated window in Oct-Nov 2025 used the UTC date instead (see
    constants.SLUG_DATE_CONVENTIONS). Probing only the ET date silently loses
    ~12% of early-2025-26 games and books them as "no market", which corrupts
    the coverage chart that gates the project.

    A miss is only `no_market` once EVERY candidate here has missed.
    """
    from datetime import date, timedelta

    a = (abbr_map or {}).get(game["away"], game["away"])
    h = (abbr_map or {}).get(game["home"], game["home"])
    d = date.fromisoformat(game["et_date"])
    return [
        ("et", f"{sport}-{a}-{h}-{d.isoformat()}"),
        ("et_plus_1", f"{sport}-{a}-{h}-{(d + timedelta(days=1)).isoformat()}"),
    ]


def slug(sport: str, game: dict, abbr_map: dict[str, str] | None = None) -> str:
    """The primary (ET) candidate only. Prefer slug_candidates for real lookups."""
    return slug_candidates(sport, game, abbr_map)[0][1]
