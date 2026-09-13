"""E10 — the NHL schedule source, named and probed.

Half the census is NHL and the plan never said where the schedule comes from.
Probed 2026-09-12 (see notes/week2-nhl-schedule.md); the facts below are
measured, not assumed:

  - `club-schedule-season/{ABBREV}/{SEASONCODE}` returns a team's whole season
    including preseason and playoffs. `gameType == 2` is the regular season.
  - 32 teams x 2 seasons = 64 calls covers both usable seasons. Every game
    appears under both of its teams, so dedupe by `id`: 1,312 unique regular
    season games per season, 2,624 total. That matches the plan's ~2,624.
  - Completed games carry final scores in `awayTeam.score` / `homeTeam.score`,
    so the winner is INDEPENDENT of Polymarket. That is what E1 needs.
  - `gameDate` is the US-Eastern date, not the UTC date and not the venue date.
    Measured: `LAK @ VGK` carries gameDate 2024-10-22 with startTimeUTC
    2024-10-23T03:00:00Z, i.e. 23:00 ET on the 22nd. So gameDate is exactly the
    slug's date convention and must never be re-derived from startTimeUTC.
  - Zero ties and zero missing scores across all 2,624 games: an NHL shootout
    win is credited as a goal, so final scores always differ. Enforced below
    rather than trusted.

Cloud egress is NOT verified. api-web.nhle.com needs no auth and sits behind a
public CDN, unlike stats.nba.com which blocks datacenter IPs, but the only
proof is a run from an Actions runner. That is the week-4 collector dry run.
"""

from __future__ import annotations

from .constants import NHL_API
from .http import Client, SchemaError, validate_schedule

# Vendored from /standings/2025-04-01 on 2026-09-12. Vendored rather than
# fetched so a census cannot silently enumerate 31 teams because one standings
# call half-failed. UTA is Utah, which entered the league in 2024-25.
NHL_TEAMS = (
    "ANA", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL", "DAL", "DET",
    "EDM", "FLA", "LAK", "MIN", "MTL", "NJD", "NSH", "NYI", "NYR", "OTT",
    "PHI", "PIT", "SEA", "SJS", "STL", "TBL", "TOR", "UTA", "VAN", "VGK",
    "WPG", "WSH",
)

REGULAR_SEASON = 2  # gameType
GAMES_PER_SEASON = 1312  # measured for both 2024-25 and 2025-26


def season_code(season: str) -> str:
    """'2024-25' -> '20242025'. Raises rather than guessing on any other shape."""
    try:
        start, end = season.split("-")
        y0 = int(start)
        y1 = int(end)
    except ValueError as e:
        raise ValueError(f"season must look like '2024-25', got {season!r}") from e
    if len(start) != 4 or len(end) != 2 or y1 != (y0 + 1) % 100:
        raise ValueError(f"season must look like '2024-25', got {season!r}")
    return f"{y0}{y0 + 1}"


def _label(team: dict, field: str) -> str:
    """Read a localized label, refusing a shape change rather than crashing on it."""
    val = team.get(field)
    if val is None:
        return ""
    if not isinstance(val, dict):
        raise SchemaError(f"NHL {field} is {type(val).__name__}, expected an object")
    return val.get("default", "")


def _side(team: dict) -> tuple[str, str, str, int | None]:
    """(abbrev lowercased, nickname, place, score) from a game's team object.

    Both labels are read from the payload per season, never vendored. Utah's
    commonName is 'Utah Hockey Club' in 2024-25 and 'Mammoth' in 2025-26, and
    the market labels that team "Utah" in both. So the resolver needs the place
    name as well as the nickname, or Utah resolves in one season and not the
    other -- which is exactly what happened before this was added.
    """
    score = team.get("score")
    abbrev = str(team.get("abbrev") or "").lower()
    if not abbrev:
        # Every other field here is strict (equal scores raise), and an empty
        # abbreviation is worse than a missing score: the game still enters the
        # denominator, every slug candidate becomes `nhl--bos-<date>` and books a
        # guaranteed no_market, AND resolve.team_labels keys on it, so two teams
        # with a blank abbreviation collide and one silently overwrites the other's
        # labels. That is the wrong-game class of error, not a missing row.
        raise SchemaError(f"NHL team object has no abbrev: {sorted(team)}")
    return (abbrev, _label(team, "commonName"), _label(team, "placeName"),
            int(score) if isinstance(score, (int, float)) else None)


def nhl_games(client: Client, season: str, *, teams: tuple[str, ...] = NHL_TEAMS,
              verbose: bool = False) -> list[dict]:
    """One row per completed regular-season game, deduped across both teams.

    Same dict shape as schedule.nba_games plus `away_name`/`home_name`,
    `away_place`/`home_place` (the labels the abbreviation resolver joins on)
    and `neutral_site`.
    """
    code = season_code(season)
    by_id: dict[int, dict] = {}
    for t in teams:
        payload = client.get_json(f"{NHL_API}/club-schedule-season/{t}/{code}",
                                  validator=validate_schedule)
        for g in (payload or {}).get("games", []):
            if g.get("gameType") != REGULAR_SEASON or g.get("id") in by_id:
                continue
            if g.get("gameState") not in ("OFF", "FINAL"):
                continue  # not played yet; not a census row and not a miss
            away, away_name, away_place, away_pts = _side(g.get("awayTeam") or {})
            home, home_name, home_place, home_pts = _side(g.get("homeTeam") or {})
            if away_pts is None or home_pts is None:
                continue
            if away_pts == home_pts:
                # Impossible since 2005 (the shootout winner is credited a
                # goal). If it ever happens the winner is undefined, and a
                # guess here would corrupt the E1 ground-truth label.
                raise ValueError(
                    f"NHL game {g['id']} on {g.get('gameDate')} has equal scores "
                    f"{away_pts}-{home_pts}; winner is undefined"
                )
            by_id[g["id"]] = {
                "game_id": str(g["id"]),
                "et_date": str(g.get("gameDate", ""))[:10],
                "away": away,
                "home": home,
                "away_name": away_name,
                "home_name": home_name,
                "away_place": away_place,
                "home_place": home_place,
                "away_pts": away_pts,
                "home_pts": home_pts,
                "winner": "home" if home_pts > away_pts else "away",
                "neutral_site": bool(g.get("neutralSite")),
                # The league's own UTC start time: the pre-tipoff cutoff
                # (PREREGISTRATION.md Amendment 1). Gamma's gameStartTime disagreed
                # by more than 15 minutes on 48 priced NHL games, including 4-5 hours
                # EARLY across Oct-Nov 2025 and a genuine 09:00 ET neutral-site game
                # in Stockholm that the ET-hour plausibility band wrongly rejected.
                "start_time_utc": g.get("startTimeUTC"),
            }
        if verbose:
            print(f"    {season} {t}: {len(by_id)} unique games so far", flush=True)
    if teams == NHL_TEAMS and len(by_id) != GAMES_PER_SEASON:
        # The measured invariant was documented and never enforced. A half-failed
        # enumeration (31 teams fetched, ~40 games short) is invisible downstream:
        # games that never enter `games` never become rows on either side of the
        # reconciliation identity, so every store guard still passes.
        raise SchemaError(
            f"NHL {season}: enumerated {len(by_id)} regular-season games, expected "
            f"{GAMES_PER_SEASON}. A short count means the 32-team fetch half-failed; "
            f"do NOT census this schedule.")
    return sorted(by_id.values(), key=lambda g: (g["et_date"], g["game_id"]))
