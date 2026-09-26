"""Games that have not been played yet: the schedule the collector needs.

The census cannot supply this. `nhl.nhl_games` and `schedule.nba_games` both
exist to build a BACKTEST denominator, so both require a finished game: the NHL
one keeps only `gameState in ("OFF", "FINAL")` with two scores, and enforces
exactly 1,312 games. Point either at 2026-27 today and it returns nothing, or
raises. Forward capture needs the opposite selection, so it gets its own module
rather than a flag that makes the census's guards conditional.

**The ET date comes from the schedule, never from the start time.** This is the
project's oldest rule (schedule.py) and this endpoint makes it easy to break:
`/schedule/{date}` returns a seven-day `gameWeek`, each day carrying its own
`date`, and the individual game objects have **`gameDate: null`**. A 22:00 ET
puck drop is 02:00Z the next calendar day, so deriving the date from
`startTimeUTC` would slug a third of the late slate one day late and find no
market. Measured while writing this: the Oct 1 slate includes games at
2026-10-02T01:30Z whose ET date is 2026-10-01.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .constants import NHL_API
from .http import Client, SchemaError

REGULAR_SEASON = 2
# gameState values that mean "not played yet". OFF/FINAL are the census's.
UPCOMING_STATES = ("FUT", "PRE")
SCHEDULE_WEEK_DAYS = 7


def _label(node: object) -> str:
    """NHL labels arrive as {"default": "Flyers"} and sometimes as a bare string."""
    if isinstance(node, dict):
        return str(node.get("default") or "")
    return str(node or "")


def _side(team: dict) -> tuple[str, str, str]:
    """(abbrev lowercased, nickname, place) for one side of an upcoming game."""
    abbrev = str(team.get("abbrev") or "").lower()
    if not abbrev:
        raise SchemaError("upcoming game has a team with no abbrev; refusing to "
                          "build a slug like nhl--bos-<date>")
    return abbrev, _label(team.get("commonName")), _label(team.get("placeName"))


def season_label(code: object) -> str:
    """20262027 -> '2026-27'. The collector stores the same shape the census does."""
    s = str(code or "")
    if len(s) != 8 or not s.isdigit():
        raise SchemaError(f"unexpected NHL season code {code!r}")
    return f"{s[:4]}-{s[6:]}"


def validate_week(payload: object) -> bool:
    """`/schedule/{date}` -> {"gameWeek": [{date, games: [...]}, ...]}.

    Cacheable only when it carries days. An empty week is a real answer in the
    off-season, and freezing one into the cache would make the collector blind
    for as long as the entry lived.
    """
    if not isinstance(payload, dict):
        raise SchemaError(f"/schedule expected an object, got {type(payload).__name__}")
    week = payload.get("gameWeek")
    if not isinstance(week, list):
        raise SchemaError("/schedule has no gameWeek list")
    for day in week:
        if not isinstance(day, dict) or "date" not in day:
            raise SchemaError("/schedule day has no date")
    return bool(week)


def nhl_upcoming(client: Client, start: date, days: int = 7, *,
                 states: tuple[str, ...] = UPCOMING_STATES,
                 bypass_cache: bool = True) -> list[dict]:
    """Regular-season NHL games not yet played, from `start` for `days` days.

    Returns the same dict shape the census uses, minus the result fields:
    `game_id`, `et_date`, `away`, `home`, the four label fields,
    `start_time_utc` and `neutral_site`. Sorted by (et_date, game_id), so the
    collector's targets are in a canonical order like everything else here.

    **`bypass_cache` defaults True, and that default is load-bearing.** The
    collector attaches an on-disk cache, and the schedule URL is keyed by date,
    so a cached week freezes the slate for the rest of the session: the 30-minute
    target refresh re-reads its own first answer and a game added, moved or
    postponed mid-session is invisible until the calendar date changes the URL.
    It also quietly broke a stated invariant. `live_quotes.game_start_time` is
    documented "re-read every poll, never cached", and `poll_target` prefers this
    module's `start_time_utc` over Gamma's (correctly: Amendment 1 established
    the league's own time is the trustworthy one, disagreeing with Gamma by up to
    360 minutes), so a cached schedule pinned both the tipoff and `secs_to_tipoff`
    to whenever the session first looked. Every other live path already bypasses:
    `resolve_targets` for `/events`, `poll_target` for `/midpoint` and `/book`.
    """
    if days < 1:
        raise ValueError("days must be >= 1")
    end = start + timedelta(days=days - 1)
    by_id: dict[str, dict] = {}
    cursor = start
    while cursor <= end:
        payload = client.get_json(f"{NHL_API}/schedule/{cursor.isoformat()}",
                                  validator=validate_week,
                                  bypass_cache=bypass_cache)
        week = (payload or {}).get("gameWeek") or []
        if not week:
            break
        last_seen = cursor
        for day in week:
            et_date = str(day.get("date"))
            day_date = date.fromisoformat(et_date)
            last_seen = max(last_seen, day_date)
            if not (start <= day_date <= end):
                continue
            for g in day.get("games") or []:
                if g.get("gameType") != REGULAR_SEASON:
                    continue
                if g.get("gameState") not in states:
                    continue
                away, away_name, away_place = _side(g.get("awayTeam") or {})
                home, home_name, home_place = _side(g.get("homeTeam") or {})
                by_id[str(g["id"])] = {
                    "sport": "nhl",
                    "season": season_label(g.get("season")),
                    "game_id": str(g["id"]),
                    # The DAY's date, not the game's: game objects here carry
                    # gameDate: null, and startTimeUTC would be a day late for
                    # every late-evening game.
                    "et_date": et_date,
                    "away": away, "home": home,
                    "away_name": away_name, "home_name": home_name,
                    "away_place": away_place, "home_place": home_place,
                    "start_time_utc": g.get("startTimeUTC"),
                    "neutral_site": bool(g.get("neutralSite")),
                }
        # The endpoint answers with a whole week; step past it rather than
        # re-requesting days already covered.
        cursor = max(last_seen + timedelta(days=1), cursor + timedelta(days=SCHEDULE_WEEK_DAYS))
    return sorted(by_id.values(), key=lambda g: (g["et_date"], g["game_id"]))


def check_season_window(client: Client, start: date, window: tuple[date, date],
                        *, scan_days: int = 45, sport: str = "nhl") -> dict:
    """Does the configured window actually contain the league's first game?

    Hand-entered dates rot: a league moves its opener and the collector
    silently no-ops through it, which looks exactly like a working off-season
    gate. This scans the real schedule from `start` and reports the first
    regular-season date it finds against the window.

    **NHL only, and it raises rather than answering for another sport.** The
    scan is `nhl_upcoming`, so pointing it at an NBA window would compare that
    window against the NHL schedule and return a confident, wrong `covered`.
    A checker that can quietly validate the wrong league is worse than no
    checker, which is the whole lesson of the window this function exists to
    catch.

    Network. Deliberately NOT part of `--dry-run`, which promises no calls.
    """
    if sport != "nhl":
        raise ValueError(
            f"check_season_window scans the NHL schedule; it cannot verify a "
            f"{sport!r} window. Wire an upcoming-games source for {sport!r} first")
    games = nhl_upcoming(client, start, days=scan_days)
    dates = sorted({g["et_date"] for g in games})
    first = date.fromisoformat(dates[0]) if dates else None
    lo, hi = window
    return {
        "scanned_from": start.isoformat(),
        "scan_days": scan_days,
        "first_game": first.isoformat() if first else None,
        "window": [lo.isoformat(), hi.isoformat()],
        "covered": bool(first and lo <= first <= hi),
        "games_found": len(games),
    }


def parse_start(value: object) -> datetime | None:
    """'2026-10-01T23:00:00Z' -> aware datetime. Naive input is refused.

    Same rule as extract._parse_gst: a naive timestamp's .timestamp() is read in
    the host zone, and the collector uses this to compute seconds-to-tipoff.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo is not None else None
