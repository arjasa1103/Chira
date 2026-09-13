# Week 2 — the census validation gate

Run on slices, not on the full census, because a label-agreement failure found
after 15,300 requests would cost a re-pull the schedule has no room for.

## What the gate checks

| Check | What it proves | Fails when |
|---|---|---|
| `label_agreement` | The market's winner equals the league's winner on every priced game (E1) | Any disagreement, or **zero priced rows** |
| `complementarity` | The two outcome tokens' last pre-tipoff prices sum to 1 | Any failure, zero checked rows, or more than 5% unchecked |
| `reconciliation` | `scheduled == priced + misses`, no orphans, no game in both tables, **and on a slice, every attempted game settled** | Any of those |
| `fault_injection` | Checks 3 actually fire: a double count AND a lost game are both injected | Either assert stays silent |
| `price_discriminates` | `p_home_close` is higher when the home team won | Sign flips, or the gap is under 2σ |
| `shuffled_join` | Reports how far agreement falls under permutation | (measurement; see the limit below) |

Checks 4 and 6 are about the instrument rather than the data.

**`price_discriminates` exists because label agreement does not cover the whole
orientation chain.** `market_winner` comes from `outcomePrices[1]`, while
`p_home_close` comes from the price series of `clobTokenIds[1]`. Label agreement
proves outcomes and outcomePrices are index-aligned to home; it says nothing
about whether clobTokenIds is aligned with them. If that leg ever flipped, every
row would still agree, complementarity would still pass, and `p_home_close`
would silently be the AWAY probability — the mirrored-curve failure the whole
design is defending against.

**A limit of `shuffled_join`, recorded so nobody over-reads it.** `census_game`
routes every disagreement to `misses`, so `priced.market_winner` equals
`games.winner` elementwise by construction and `true_rate` is 1.0 whatever the
join does. The permuted rate then lands at the chance rate as arithmetic. It is
a useful measurement of the chance level and a guard on the join key; it is NOT
independent evidence that the join is correct. The real E1 evidence is
`count(misses where reason='label_disagreement') == 0`, which check 1 queries.

## Results: all four sport-seasons PASS

Numbers are from `data/gate-<sport>-<season>.json`. Every slice is a 200-game
**stride** across its season.

| Sport | Season | Attempted | Priced | Label agreement | Discrimination |
|---|---|---|---|---|---|
| NBA | 2024-25 | 200 | 200 (100%) | 200/200 | gap 0.161, 5.9σ |
| NHL | 2024-25 | 200 | 136 (68%) | 136/136 | gap 0.057, 2.7σ |
| NBA | 2025-26 | 200 | 199 (99.5%) | 199/199 | gap 0.208, 7.6σ |
| NHL | 2025-26 | 200 | 200 (100%) | 200/200 | gap 0.042, 3.0σ |

**735 priced games, 735 agreements, zero disagreements**, complementarity clean
on all 735, and the token leg independently verified in all four.

> **Correction, 2026-09-12.** An earlier version of this note reported 960
> priced games and NHL 2024-25 coverage of 40%. Two of the four slices were
> contaminated: the first NBA 2024-25 run predated the `nba_games` sort fix and
> censused the LAST 200 games of the season, and the first NHL 2024-25 run
> predated the stride strategy and censused the FIRST 200 in date order. Later
> stride runs were then layered on top by resume rather than replacing them. The
> NBA sample was 57% March-April against a schedule that is 28%, and the NHL
> "40% coverage" was an artifact of a sample that was 58% October-November. Both
> were discarded and re-run clean; the table above is the clean result. The
> per-month attempted/scheduled breakdown now ships in every gate report so this
> is visible rather than forensic.

Store state: 5,084 scheduled, 735 priced, 65 misses, 4,284 pending.

**NHL's discrimination is roughly 3x weaker than NBA's** (gap 0.04-0.06 vs
0.16-0.21). That is a real property of the sport, not a data problem, and it
bears on which sport should be primary.

### The second date convention earns its keep, and only in 2025-26

| Sport | Season | `et` | `et_plus_1` | Months where `et_plus_1` fired |
|---|---|---|---|---|
| NBA | 2024-25 | 400 | 0 | — |
| NHL | 2024-25 | 161 | 0 | — |
| NBA | 2025-26 | 184 | 15 | 2025-10 (5), 2025-11 (10) |
| NHL | 2025-26 | 189 | 11 | 2025-12 (11) |

**26 of 960 games would have been recorded as `no_market` without the second
candidate**, and zero of 561 games in 2024-25 needed it. This is the week-1
slug-convention correction confirmed on census data rather than on a 90-game
probe.

**One correction to week 1.** The week-1 note said the upstream slug bug looked
"fixed around late November 2025". NBA agrees, but **all 11 NHL `et_plus_1`
hits are in December 2025**, so the convention change is not simultaneous
across sports. Treat the ET/UTC window as sport-specific and keep probing both
candidates for the whole of 2025-26.

### Per-game liquidity, measured on the clean slices

Median terminal volume on priced games:

| Sport | 2024-25 | 2025-26 | Ratio |
|---|---|---|---|
| NBA | $313k | $1.88M | 6.0x |
| NHL | $58k | $614k | 10.6x |

The plan's 2025-26 NBA figure (~$1.9M) is confirmed. Its 2024-25 figure
(~$500k) came from a small probe and **measures $313k here**, so the
between-season liquidity contrast is larger than planned, not smaller. NHL is
roughly 5x thinner than NBA in BOTH seasons, which is the part that matters for
headline 2: pooling sports would make "liquidity" and "sport" the same cut, on
top of the already-documented liquidity/season-regime confound.

**Read the 2024-25 figure with the within-season trend in mind.** Monthly NBA
medians run $64k in October to $437k in February, so any sample that is not
uniform across the season will produce a misleading median. This one is a
stride; the earlier contaminated one was not, and it happened to land on a
similar number for the wrong reason.

## Two coverage findings that change what the charts will show

### Polymarket's NHL coverage starts in December 2024, not October

Attempted games by month, NHL 2024-25, on the clean stride slice:

| Month | Attempted | Priced | Coverage |
|---|---|---|---|
| 2024-10 | 26 | 0 | 0.00 |
| 2024-11 | 33 | 0 | 0.00 |
| 2024-12 | 33 | 29 | 0.88 |
| 2025-01 | 34 | 33 | 0.97 |
| 2025-02 | 19 | 19 | 1.00 |
| 2025-03 | 35 | 35 | 1.00 |
| 2025-04 | 20 | 20 | 1.00 |

All 59 October-November games came back `no_market` and **all survived a
cache-bypassed re-probe**, so this is absence of markets and not a transient
failure. The conclusion is unchanged from the contaminated sample, and it now
rests on a sample that is uniform across the season.

**One caveat that stands.** `no_market` now means "every candidate slug returned
an empty event list"; a slug that returned events whose labels did not match is
a separate reason (`label_mismatch_at_slug`) as of the week-2 review. But the
abbreviation map behind those slugs was confirmed from a single January game per
team, so a WITHIN-season convention change would still present as a run of
`no_market`. Week 1 established that conventions drift across seasons and week 2
established that the DATE convention drifts mid-season, so this is not a
hypothetical. Consequences:

- The early-season stratum for headline 2 does not exist for NHL 2024-25. The
  "early season" cut has to be defined within the covered window, or it is a
  comparison between a sport-season that has data and one that does not.
- NHL's usable n for 2024-25 is roughly 1,000, not 1,312.

### NHL per-game volume is about 5x thinner than NBA

Mean terminal volume on priced games: **NBA $374k, NHL $73k**. Both are 2024-25,
the thin season. This matters for the liquidity strata in headline 2: pooling
sports would make "liquidity" and "sport" the same cut, which is the same
confound already documented for liquidity and season regime.

## A slicing bug the gate surfaced immediately

The first NHL gate slice took the first 200 games **in date order** and returned
**0 priced, 200 misses** — a gate with nothing to validate. Two fixes:

1. `census.slice_games` gained a `stride` strategy (every k-th game across the
   season), now the default for limited runs.
2. `schedule.nba_games` was not sorted. `nba_api`'s `LeagueGameFinder` returns
   newest first, so `--limit 200` censused the **last** 200 games of the season
   while the flag said it took the earliest. Both schedule sources now return
   `(et_date, game_id)` order.

## Price sanity

| | NBA 2024-25 | NHL 2024-25 |
|---|---|---|
| mean `p_home_close` | 0.535 | 0.521 |
| mean seconds before tip | 56.5 | 56.1 |

Mean seconds between the last quote and tipoff moved between seasons, 56s in
2024-25 to 43s in 2025-26. Small, but it is a property of the closing-price
construction and belongs in the writeup rather than being discovered in week 9.

## What was NOT established

- **No full-pass reconciliation yet.** Both runs are slices, so `balanced` is
  False by construction and the gate checks the instant-by-instant invariants
  (no orphans, no double-counting, pending never negative) instead. The
  `scheduled == priced + misses` identity is only asserted on a complete pass,
  which is week 3.
- **Coverage percentages here are not the coverage chart.** The slices are
  deliberately spread across the season, so they are unbiased with respect to
  season phase but they are still slices. The Phase 2 chart needs the full census.
- **The re-probe cannot distinguish "market never existed" from "market existed
  and was deleted."** Both present as an empty `/events?slug=`.
