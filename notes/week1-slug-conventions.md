# T3 — abbreviation maps and the slug date convention (week 1)

**Status: DONE, and it overturned a fact previously recorded as verified.**

## Abbreviation map: identity, for both usable seasons

`nba_api` team abbreviations, lowercased, equal Polymarket's slug abbreviations
**exactly** for NBA in 2024-25 and 2025-26. Set difference is empty in both directions,
30/30 teams. No translation table is needed for NBA in the usable window.

The `no` (2023) vs `nop` (2025) drift that motivated per-season learning is real but lives
entirely in 2023-24, which is excluded. Keep the per-season learner anyway: it cost 180
requests and it is the only thing that would catch a future drift.

NHL learned 32/32 for 2025-26 and 32/32 for 2024-25 from Polymarket alone.

## Exhibition entities contaminate a naive learner

The learner initially reported 34/30 NBA and 36/32 NHL. The extras are not teams:

- NBA 2024-25: `cgs`=Chuck's Global Stars, `crs`=Candace's Rising Stars,
  `kys`=Kenny's Young Stars, `sog`=Shaq's OGs — All-Star Rising Stars squads.
- NHL 2024-25: `cannhl`=Canada, `finnhl`=Finland, `swenhl`=Sweden, `usanhl`=USA —
  4 Nations Face-Off.

Subtract them and it is exactly 30 and 32. These are concrete instances for the E19
special-games reason enum, found a season earlier than the plan expected. The census must
route them to an explicit enum, not treat them as league games.

## The slug date convention is NOT always ET (correction)

An earlier probe of 11 games concluded "the slug date is always the US-Eastern game date."
**That was wrong**, and the sample was the reason: all 11 sat on one side of a convention
change. Probing 90 stratified games across both seasons:

| Window | ET | UTC | Miss |
|---|---|---|---|
| 2025-26 Oct | 2 | **1** | 0 |
| 2025-26 Nov | 6 | **3** | 0 |
| 2025-26 Dec-Apr | 33 | 0 | 0 |
| 2024-25 (all) | 45 | 0 | 0 |

Decisive per-game evidence:

| slug | gameStartTime | UTC date | ET date | slug uses |
|---|---|---|---|---|
| `nba-was-okc-2025-10-31` | 10-31 00:00Z | 10-31 | 10-30 | UTC |
| `nba-phx-uta-2025-10-28` | 10-28 01:00Z | 10-28 | 10-27 | UTC |
| `nba-chi-cle-2025-11-09` | 11-09 01:00Z | 11-09 | 11-08 | UTC |
| `nba-mem-sac-2025-11-30` | 12-01 02:00Z | 12-01 | 11-30 | ET |
| `nhl-wsh-chi-2026-01-09` | 01-10 01:00Z | 01-10 | 01-09 | ET |

Not sport-based and not tipoff-hour-based: rows 2 and 5 share an 01:00Z tipoff and disagree.
Most likely an upstream slug-generation bug fixed around late November 2025.

**Consequence, now encoded in `schedule.slug_candidates()`:** try the ET date AND ET+1 for
every game. A miss is only `no_market` after every candidate misses. Trying ET alone loses
~12% of early-2025-26 games and books them as missing markets, corrupting the coverage chart
that gates the project.

## Coverage is far better than assumed

130 NBA games probed (40 random + 90 stratified), across both usable seasons:
**129 found, 1 confirmed no-market** (`nba-dal-mil-2026-03-31`, all 5 variants missed).

That is **~99% coverage**, against a plan that treated density as the open question gating
everything. The census will still measure it properly across all 2,460 games, but the
project's viability question is effectively answered for NBA: the data is there.
