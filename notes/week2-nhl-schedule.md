# Week 2 — the NHL schedule source (E10)

**Probed 2026-09-12.** Every number below came from a live call, not from docs.

## Source

`https://api-web.nhle.com/v1/club-schedule-season/{ABBREV}/{SEASONCODE}`

- `SEASONCODE` is `20242025` / `20252026`.
- Returns a team's entire season: preseason, regular season, playoffs.
  `gameType == 2` selects the regular season.
- 32 teams x 2 seasons = **64 calls** covers both usable seasons. Every game
  appears under both of its teams, so dedupe on `id`.

Measured: **1,312 unique regular-season games per season, 2,624 total.** The plan
estimated ~2,624, so the census request budget needs no revision.

## What it gives that the census needs

| Need | Field | Status |
|---|---|---|
| Slug date | `gameDate` | **US-Eastern date.** Verified below. |
| Away / home | `awayTeam.abbrev`, `homeTeam.abbrev` | Present |
| Independent winner | `awayTeam.score`, `homeTeam.score` | Present on completed games |
| Team labels for the abbreviation join | `commonName.default`, `placeName.default` | Present, and season-specific |
| Neutral site | `neutralSite` | Present: 6 games in 2024-25, 4 in 2025-26 |

### `gameDate` is the ET date, not the UTC date and not the venue date

`LAK @ VGK` carries `gameDate` `2024-10-22` with `startTimeUTC`
`2024-10-23T03:00:00Z`, i.e. 23:00 ET on the 22nd. So `gameDate` is exactly the
slug convention and must never be re-derived from `startTimeUTC` (the same rule
`schedule.py` already enforces for `nba_api`'s `GAME_DATE`).

### Winners are always resolvable

Across all 2,624 games: **zero ties and zero missing scores.** An NHL shootout
win is credited as a goal, so final scores always differ. `nhl.py` raises on
equal scores rather than trusting this, because a guess there would corrupt the
E1 ground-truth label.

`gameOutcome.lastPeriodType` distributions, for reference:
2024-25 REG 1041 / OT 194 / SO 77; 2025-26 REG 986 / OT 207 / SO 119.

### Team labels change between seasons

Utah's `commonName.default` is `Utah Hockey Club` in 2024-25 and `Mammoth` in
2025-26, while Polymarket labels that team `Utah` in both. Nicknames are
therefore read from the payload per season and never vendored.

## What was NOT established

- **Cloud egress is unverified.** `api-web.nhle.com` needs no auth and sits
  behind a public CDN, unlike `stats.nba.com`, which blocks datacenter IPs. But
  "probably fine from Actions" is not a measurement. The only proof is a run
  from a runner, which is the week-4 collector dry run. Until then, treat NHL
  schedule access from CI as unproven.
- **No rate limit was observed** at 3-4 rps across 65-173 requests. No 429 at
  any point. That is not the same as knowing the limit.
- **Only regular season is probed.** Playoff and preseason slug conventions on
  Polymarket are untested and out of scope.
- `/schedule/{date}` (a week per call) and `/score/{date}` also work and carry
  the same `gameDate` semantics. They are not used, because the per-team call
  gets a whole season in one request.
