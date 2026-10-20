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

from datetime import UTC, date, datetime, timedelta

from .constants import ESPN_NBA_API, NHL_API
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


# --- NBA -----------------------------------------------------------------
#
# ESPN's abbreviations are not the census's for six teams. Read from
# `.../nba/teams` on 2026-10-20 (all 30) and diffed against the 30 codes in
# `data/abbr_map_resolved.json`; the other 24 are identical once lowercased.
# Vendored rather than fetched: a translation table that can change under the
# collector mid-season is a table that can silently stop resolving markets,
# and `scripts/fetch_espn_nba_codes.py` re-runs the diff and exits non-zero.
ESPN_TO_CENSUS = {"gs": "gsw", "no": "nop", "ny": "nyk", "sa": "sas",
                  "utah": "uta", "wsh": "was"}

# ESPN writes the Clippers' city as "LA" and the Lakers' as "Los Angeles".
# `resolve.team_labels` only accepts a place name that is UNIQUE in the
# league, precisely so a Lakers/Clippers slug cannot confirm with the sides
# swapped. Two different spellings both look unique and quietly defeat that
# guard, so they are collapsed to one before it runs.
ESPN_PLACE_FIXES = {"LA": "Los Angeles"}

# ESPN's `status.type.state`. "pre" is not-yet-started; the collector's window
# computation wants every state, for the same reason ALL_GAME_STATES exists.
NBA_UPCOMING_STATES = ("pre",)
NBA_ALL_STATES = ("pre", "in", "post")

# How long after a scheduled tipoff a game may still say "pre" before this
# module stops believing the clock. See `nba_upcoming`.
STALE_PRE_GRACE = timedelta(minutes=20)


def nba_season_label(year: object) -> str:
    """ESPN's season year is the END year: 2027 -> '2026-27'."""
    try:
        y = int(str(year))
    except (TypeError, ValueError):
        raise SchemaError(f"unexpected ESPN season year {year!r}") from None
    if not 1950 <= y <= 2100:
        raise SchemaError(f"implausible ESPN season year {year!r}")
    return f"{y - 1}-{str(y)[2:]}"


def espn_abbrev(code: object) -> str:
    """ESPN team code -> the census's. Raises rather than guessing."""
    c = str(code or "").strip().lower()
    if not c:
        raise SchemaError("ESPN competitor has no abbreviation; refusing to "
                          "build a slug from a blank side")
    return ESPN_TO_CENSUS.get(c, c)


def validate_scoreboard(payload: object) -> bool:
    """`/scoreboard?dates=YYYYMMDD` -> {"events": [...]}.

    Cacheable only when it carries events, for `validate_week`'s reason: a
    dark day is a real answer and freezing one would blind the collector for
    as long as the entry lived.
    """
    if not isinstance(payload, dict):
        raise SchemaError(f"/scoreboard expected an object, got "
                          f"{type(payload).__name__}")
    events = payload.get("events")
    if not isinstance(events, list):
        raise SchemaError("/scoreboard has no events list")
    return bool(events)


def _espn_side(competitor: dict) -> tuple[str, str, str]:
    """(census abbrev, nickname, place) for one side of an ESPN event."""
    team = competitor.get("team") or {}
    place = str(team.get("location") or "")
    return (espn_abbrev(team.get("abbreviation")),
            str(team.get("name") or ""),
            ESPN_PLACE_FIXES.get(place, place))


def nba_upcoming(client: Client, start: date, days: int = 7, *,
                 states: tuple[str, ...] = NBA_UPCOMING_STATES,
                 bypass_cache: bool = True,
                 now: datetime | None = None) -> list[dict]:
    """Regular-season NBA games from `start` for `days` days, via ESPN.

    Same dict shape as `nhl_upcoming`, so `resolve_targets`,
    `upcoming_targets` and `poll_target` need no NBA branch.

    **The ET date is the date requested, never the event's timestamp.** The
    endpoint is queried one day at a time and groups games by US calendar day,
    so a 21:30 ET tipoff in San Antonio arrives under `dates=20261020` with
    `date: 2026-10-21T01:30Z`. Deriving the date from that timestamp would
    slug the whole late slate one day forward and find no market -- the same
    trap `nhl_upcoming` documents, in a different shape. One request per day
    rather than ESPN's `dates=A-B` range form, because a range response gives
    no per-day attribution and would force exactly that derivation.

    **ESPN's tipoff time is third-party and is not trusted past its own
    deadline.** Amendment 1 established the league's own time as the
    trustworthy one, and for the NHL this module reads it from the league.
    There is no reachable NBA equivalent (see `constants.ESPN_NBA_API`), and
    ESPN's times have been seen to look like placeholders: on 2026-10-20,
    opening day, it published BOS@DET as 19:00Z / "3:00 PM EDT" on a slate
    whose other two games were 19:00 and 21:30 ET.

    So when a game's scheduled time is more than `STALE_PRE_GRACE` in the past
    and ESPN still reports it as not started, `start_time_utc` comes back
    **None** instead of a time this function can see is wrong. That is not a
    special case: `collector.upcoming_targets` already KEEPS games whose start
    time is unknown, by documented design, and `live_quotes.secs_to_tipoff`
    is nullable. The alternative is worse in exactly the way that matters --
    `upcoming_targets` drops a game 30 minutes past its scheduled tipoff, so
    one bad time silently ends pre-game capture for that game, and pre-game
    prices cannot be fetched later.

    A game that ESPN reports as `in` or `post` keeps its time: it started, so
    the clock is corroborated by something other than itself.
    """
    if days < 1:
        raise ValueError("days must be >= 1")
    n = (now or datetime.now(UTC)).astimezone(UTC)
    out: dict[str, dict] = {}
    for offset in range(days):
        day = start + timedelta(days=offset)
        payload = client.get_json(
            f"{ESPN_NBA_API}/scoreboard?dates={day.strftime('%Y%m%d')}",
            validator=validate_scoreboard, bypass_cache=bypass_cache)
        for ev in (payload or {}).get("events") or []:
            comps = (ev.get("competitions") or [{}])[0]
            season = ev.get("season") or {}
            if str(season.get("slug") or "") != "regular-season":
                # Preseason runs to 2026-10-16 and the NBA window opens
                # 2026-10-15, so two preseason days fall inside it.
                continue
            status = ((comps.get("status") or {}).get("type") or {})
            state = str(status.get("state") or "")
            if state not in states:
                continue
            sides = comps.get("competitors") or []
            if len(sides) != 2:
                raise SchemaError(f"ESPN event {ev.get('id')!r} has "
                                  f"{len(sides)} competitors, expected 2")
            by_side = {str(s.get("homeAway") or ""): s for s in sides}
            if set(by_side) != {"home", "away"}:
                raise SchemaError(f"ESPN event {ev.get('id')!r} does not have "
                                  f"one home and one away side")
            away, away_name, away_place = _espn_side(by_side["away"])
            home, home_name, home_place = _espn_side(by_side["home"])
            start_utc = parse_start(ev.get("date"))
            if (start_utc is not None and state == "pre"
                    and start_utc < n - STALE_PRE_GRACE):
                start_utc = None
            out[str(ev["id"])] = {
                "sport": "nba",
                "season": nba_season_label(season.get("year")),
                "game_id": str(ev["id"]),
                "et_date": day.isoformat(),
                "away": away, "home": home,
                "away_name": away_name, "home_name": home_name,
                "away_place": away_place, "home_place": home_place,
                "start_time_utc": (None if start_utc is None
                                   else start_utc.isoformat().replace(
                                       "+00:00", "Z")),
                # ESPN's own flag, passed through unverified. The census does
                # NOT use it: the league's `isNeutral` was wrong for all four
                # 2023-24 neutral games, so the feature store derives neutral
                # sites from a vendored arena list instead
                # (notes/week7-neutral-and-holdout.md). Nothing in the
                # collector reads this column; it is stored for the record.
                "neutral_site": bool(comps.get("neutralSite")),
            }
    return sorted(out.values(), key=lambda g: (g["et_date"], g["game_id"]))


UPCOMING_BY_SPORT = {"nhl": nhl_upcoming, "nba": nba_upcoming}

# Every schedule state each source can report, not only the not-yet-played
# ones. The collector's window computation needs these: a run arriving while
# the day's matinee is being played must compute the SAME opening as one
# that arrived before it, or the window would jump back to 16:00 ET
# mid-afternoon. The two leagues spell their states differently, which is
# why this is a table and not one tuple.
ALL_STATES_BY_SPORT = {
    "nhl": ("FUT", "PRE", "LIVE", "CRIT", "OFF", "FINAL"),
    "nba": NBA_ALL_STATES,
}


def check_season_window(client: Client, start: date, window: tuple[date, date],
                        *, scan_days: int = 45, sport: str = "nhl") -> dict:
    """Does the configured window actually contain the league's first game?

    Hand-entered dates rot: a league moves its opener and the collector
    silently no-ops through it, which looks exactly like a working off-season
    gate. This scans the real schedule from `start` and reports the first
    regular-season date it finds against the window.

    **It scans the sport it was asked about, and raises for a sport with no
    enumerator.** The scan used to be `nhl_upcoming` unconditionally, so
    pointing it at an NBA window compared that window against the NHL
    schedule and returned a confident, wrong `covered`. A checker that can
    quietly validate the wrong league is worse than no checker, which is the
    whole lesson of the window this function exists to catch. It now
    dispatches through `UPCOMING_BY_SPORT`, and an unknown sport raises as
    before rather than falling back to any league's schedule.

    Network. Deliberately NOT part of `--dry-run`, which promises no calls.
    """
    enumerate_sport = UPCOMING_BY_SPORT.get(sport)
    if enumerate_sport is None:
        raise ValueError(
            f"check_season_window has no upcoming-games source for {sport!r}; "
            f"it can scan {sorted(UPCOMING_BY_SPORT)}. Wire one first rather "
            f"than letting it verify a window against another league")
    games = enumerate_sport(client, start, days=scan_days)
    dates = sorted({g["et_date"] for g in games})
    first = date.fromisoformat(dates[0]) if dates else None
    lo, hi = window
    return {
        "sport": sport,
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
