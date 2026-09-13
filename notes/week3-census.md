# Week 3 — the full census and the snapshot

**Status:** done 2026-09-13. The validation gate passes all seven checks on all four sport-seasons. All 5,084 scheduled games in the two usable seasons are settled:
**4,661 priced, 423 classified misses, 145.6M raw price rows**.
Snapshot: `data/snapshots/census-20260913-224d6ad985e0/` (162 MB; store digest
`224d6ad985e09d71f542388f8d14e908e4d94efe5f4b5b5b00c956a6a597ef52`; cut from commit `1013d72`).

The census ran more than once. That's the story of the week: the first full pass
reconciled on every sport-season, then failed the validation gate on both 2025-26
seasons. Following those failures turned up two real defects that had been passing
every check on most games.

## Results

| Sport | Season | Scheduled | Priced | Misses | Coverage | Median volume | `et` / `et_plus_1` |
|---|---|---|---|---|---|---|---|
| NBA | 2024-25 | 1,230 | 1,229 | 1 | 99.9% | $296k | 1,229 / 0 |
| NHL | 2024-25 | 1,312 | 896 | 416 | 68.3% | $56k | 896 / 0 |
| NBA | 2025-26 | 1,230 | 1,226 | 4 | 99.7% | $2.03M | 1,137 / 89 |
| NHL | 2025-26 | 1,312 | 1,310 | 2 | 99.8% | $604k | 1,241 / 69 |

Every priced game carries all of: an independent league winner that agrees with the
market (label agreement), a verified token leg (`price_discriminates`), the full-game
moneyline selected by type, a close cut at the league's own tipoff, the close under the
original pre-registered cutoff for audit, T-1h/T-6h/T-24h looks, and the raw minute
series for both tokens.

Miss reasons: 421 `no_market`, 2 `no_pre_tipoff_points` (NBA 2025-26).

## Finding 1: spread markets were being priced as moneylines

`confirm()` took the first market whose outcome labels matched the two teams. Gamma events
also hold `Spread: Capitals (-1.5)` and, for NBA 2025-26, a first-half moneyline, with the
same two team names as outcomes.

- **5 NHL 2025-26 spreads were priced as moneylines and passed every check.** Label agreement
  caught 2 more, only because the favourite won by exactly one goal, which split the spread
  from the moneyline. All 7 were April 2026.
- **The exposure was much wider than the damage.** 1,212 NBA 2025-26 events and 580 NHL
  2025-26 events held another label-matching market; they got the moneyline only because it
  happened to be listed first.
- Every cached event carries `sportsMarketType`, so the census now selects on it. It isn't
  perfect: 40 NBA 2024-25 single-market "Thunder vs. X" moneylines are typed `totals`
  upstream. A real totals market has Over/Under outcomes and can't label-match two teams, so
  a *sole* label-matching market is accepted unless its type names a spread or partial game.

After the fix: 1,189 + 40 NBA 2024-25 and every other priced game is a moneyline, and both
label disagreements disappeared.

## Finding 2: Gamma's `gameStartTime` is not a trustworthy tipoff (Amendment 1)

The close is cut "at or before `gameStartTime`", and that timestamp comes from the party
being benchmarked. Against the leagues' own start times (NHL `startTimeUTC`, NBA
`scheduleleaguev2`), on the final census:

| Sport | Season | Off by >15 min | Late | Early | Off by >1 h | Close changed |
|---|---|---|---|---|---|---|
| NBA | 2024-25 | 7 | 4 | 3 | 2 | 7 |
| NHL | 2024-25 | 2 | 1 | 1 | 1 | 2 |
| NBA | 2025-26 | 16 | 13 | 3 | 5 | 16 |
| NHL | 2025-26 | 51 | 8 | 43 | 43 | 40 |

- **Late** timestamps let in-game prices into the "close", up to 360 minutes late.
  `nba-dal-uta-2024-11-14` is the clearest case: Gamma's tipoff is 237 minutes late, the
  original-definition close is 0.9995 on a 115-113 game, and the close cut at the league's
  tipoff is **0.26**.
- **Early** timestamps cut the close hours before tipoff. 41 NHL 2025-26 games are exactly
  240 minutes early (October 2025, daylight time) or 300 minutes early (November, after it
  ended): Eastern wall-clock time recorded as UTC.
- The interim ET-hour plausibility band passed those, and rejected a genuine 09:00 ET NHL
  game in Stockholm (`nhl-nsh-pit-2025-11-16`, neutral site).

The close is now cut at the league's start time for all 4,661 priced games. That changes a
pre-registered definition, so it's recorded as PREREGISTRATION.md Amendment 1, adopted before
any model fit or census calibration statistic and chosen from timestamp disagreement alone.
`p_home_close_gamma` keeps the original-definition close on every row; it differs from the
adopted close on 65 games.

## Finding 3: the complementarity check compared quotes from different moments

The first pass reported 3 complementarity failures (sums 0.995, 0.995, 1.01). The two tokens'
price series are sampled independently: at identical timestamps in 2024-25, but a median 5 s
and a p90 59 s apart in 2025-26. Comparing each series' own last point compared two
different moments. At every timestamp both NHL markets shared, they summed to exactly
1.000000 (24/24 and 830/830).

The first fix, comparing only at an exact shared timestamp, over-corrected: 57% of NBA and
40% of NHL 2025-26 games had none, and the gate failed them as unchecked instead of passing
them quietly. The rule adopted was measured on the census itself. Pair each home quote in
the last 2 hours with the latest away quote at most 60 s before it, require at least 10
pairs, and pass when at least half the pairs sum to 1 within 1e-6.

| Sport-season | Fewest pairs on any game | Lowest share on any game |
|---|---|---|
| NBA 2024-25 | 60 | 0.9917 |
| NHL 2024-25 | 120 | 0.9917 |
| NBA 2025-26 | 77 | 0.5755 |
| NHL 2025-26 | 74 | 0.6931 |

The worst per-pair error on any game was 0.03, which is the price moving between two samples.
A market that isn't a true complement misses at every pair. Tighter 15-30 s pairing was
unstable: hundreds of games got no pairs at all. All 4,661 priced games now pass, and the
per-game evidence is stored as `complement_share` and `complement_pairs`.

## Finding 4: NHL 2024-25 coverage starts in December, now on the full season

| Month | Scheduled | Priced |
|---|---|---|
| 2024-10 | 166 | 0 |
| 2024-11 | 220 | 0 |
| 2024-12 | 214 | 188 |
| 2025-01 | 224 | 220 |
| 2025-02 | 122 | 122 |
| 2025-03 | 234 | 234 |
| 2025-04 | 132 | 132 |

All 416 misses are `no_market` and survived a cache-bypassed re-probe in two separate runs
hours apart. The week-2 conclusion from 200-game slices holds on the whole season.

## Finding 5: the liquidity picture held

Full-census medians ($296k and $2.03M NBA; $56k and $604k NHL) are close to the week-2
stride-slice estimates ($313k, $1.88M, $58k, $614k). NHL is still roughly 3-5x thinner than
NBA within each season, and the 2025-26 regime is 7-11x more liquid than 2024-25.

## Smaller findings that constrain later weeks

- **NHL 2025-26 markets open ~27 days before the game** (4-7 days for the other three), which
  is why it holds 96.1M of the 145.6M raw rows. Zero duplicate rows anywhere.
- **T-24h is often missing in 2024-25:** null on 100 NBA and 33 NHL priced games, because
  those markets opened less than a day before tipoff; essentially never missing in 2025-26.
  The time-to-close stratum in headline 2 is therefore not balanced across seasons.
- **Stale closes are common and rising:** a flat run of 10+ identical pre-tipoff minutes on
  31% (NBA 2024-25), 43% (NHL 2024-25), 52% (NBA 2025-26) and 50% (NHL 2025-26) of priced
  games. The pre-registered staleness sensitivity split matters more than planned.
- **The second slug date convention is load-bearing only in 2025-26:** 89 NBA and 69 NHL games.
- **The last quote lands closer to tipoff in 2025-26** (mean 44 s vs 56 s).

## Operational: a sleeping laptop killed the census twice

Both resumes died on DNS failures. The macOS power log shows the machine in Deep Idle sleep
with the lid closed, running only in ~45-second maintenance wakes. A single request
exhausting its retries used to end the run. `http.NetworkUnavailable` now distinguishes
"this machine can't reach the network" from an upstream failure (it doesn't trip the circuit
breaker), and the census waits it out with capped backoff for up to 2 hours, retrying the
same game. Runs are launched under `caffeinate -i`. Nothing was lost either time, because
every completed game was already in the store.

**The first snapshot cut filled the disk.** `COPY ... ORDER BY` over 145.6M raw price rows
spilled about 6 GB of uncompressed sort runs to DuckDB's temp directory, and free space fell
from 6.5 GB to 493 MB before it failed. DuckDB and the snapshot writer both cleaned up, and
the store was verified intact. The same rows written unsorted streamed at 1.44 bytes per
row with no spill, so `price_points` is now written unsorted (readers `ORDER BY`), and a
snapshot refuses to start without room. The final snapshot is 162 MB.

## What was NOT established

- **Nothing about calibration.** No Brier, ECE or slope has been computed on the census. The
  pre-registered analysis runs on the snapshot, starting week 4.
- **The 4,661 moneyline selections are only as good as `sportsMarketType` plus the sole-match
  fallback.** 40 selections rely on the fallback; they all passed label agreement and the
  token-leg check, which is evidence but not proof.
- **League start times are trusted as ground truth.** They were not cross-checked against a
  third source, and a postponed or moved game would carry the league's final time.
- **Polymarket's terms of use are still unresolved (E18).** The snapshot is a local input,
  gitignored under `data/`, not a public dataset release.
