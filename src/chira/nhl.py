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

from .http import Client

NHL_API = "https://api-web.nhle.com/v1"

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


def _side(team: dict) -> tuple[str, str, str, int | None]:
    """(abbrev lowercased, nickname, place, score) from a game's team object.

    Both labels are read from the payload per season, never vendored. Utah's
    commonName is 'Utah Hockey Club' in 2024-25 and 'Mammoth' in 2025-26, and
    the market labels that team "Utah" in both. So the resolver needs the place
    name as well as the nickname, or Utah resolves in one season and not the
    other -- which is exactly what happened before this was added.
    """
    score = team.get("score")
    return (
        str(team.get("abbrev", "")).lower(),
        (team.get("commonName") or {}).get("default", ""),
        (team.get("placeName") or {}).get("default", ""),
        int(score) if isinstance(score, (int, float)) else None,
    )


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
        payload = client.get_json(f"{NHL_API}/club-schedule-season/{t}/{code}")
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
            }
        if verbose:
            print(f"    {season} {t}: {len(by_id)} unique games so far", flush=True)
    return sorted(by_id.values(), key=lambda g: (g["et_date"], g["game_id"]))
