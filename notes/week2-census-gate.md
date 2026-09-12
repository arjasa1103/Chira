# Week 2 — the census validation gate

Run on slices, not on the full census, because a label-agreement failure found
after 15,300 requests would cost a re-pull the schedule has no room for.

## What the gate checks

| Check | What it proves | Fails when |
|---|---|---|
| `label_agreement` | The market's winner equals the league's winner on every priced game (E1) | Any disagreement, or **zero priced rows** |
| `complementarity` | The two outcome tokens' last pre-tipoff prices sum to 1 | Any failure, or zero checked rows |
| `reconciliation` | `scheduled == priced + misses`, no orphans, no game in both tables | Any of those |
| `fault_injection` | Check 3 actually fires when the store is corrupted | The assert stays silent |
| `shuffled_join` | Agreement collapses to chance under permutation | Agreement survives, or the label column has no power |

The last two test the tests. An assert nobody has watched fail is an assert
nobody knows is wired up, and a 100% agreement rate is equally consistent with
a perfect join and a degenerate one.

## Results

Both sports pass. Numbers are from `data/gate-<sport>-<season>.json`.

| Sport | Season | Priced | Label agreement | Complementarity | Shuffled vs chance |
|---|---|---|---|---|---|
| NBA | 2024-25 | 200 | 200/200 agree | 200/200 ok | 0.500 vs 0.500 |
| NHL | 2024-25 | 161 | 161/161 agree | 161/161 ok | 0.516 vs 0.507 |

**361 independent confirmations of the orientation chain**, on top of week 1's
128. A flip would have mirrored the calibration curve about 0.5 and looked like
a finding.

## Two coverage findings that change what the charts will show

### Polymarket's NHL coverage starts in December 2024, not October

Attempted games by month, NHL 2024-25:

| Month | Attempted | Priced | Coverage |
|---|---|---|---|
| 2024-10 | 166 | 0 | 0.00 |
| 2024-11 | 68 | 0 | 0.00 |
| 2024-12 | 38 | 34 | 0.89 |
| 2025-01 | 41 | 40 | 0.98 |
| 2025-02 | 22 | 22 | 1.00 |
| 2025-03 | 42 | 42 | 1.00 |
| 2025-04 | 23 | 23 | 1.00 |

All 234 October-November games came back `no_market`, and **all 234 survived a
cache-bypassed re-probe**, so this is absence of markets and not a transient
failure or a slug bug. Consequences:

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

## Price sanity on the 361 priced games

| | NBA | NHL |
|---|---|---|
| mean `p_home_close` | 0.550 | 0.543 |
| range | 0.085 - 0.966 | 0.245 - 0.805 |
| mean seconds before tip | 54.8 | 56.1 |
| stale flat run | 70/200 (35%) | 70/161 (43%) |

The stale-flat-run rate matches week 1's independent measurement of 41% on 128
games, which is a small independent check that the flag means the same thing in
the census as it did in the probe.

## What was NOT established

- **Nothing about 2025-26 coverage.** Both gate runs are 2024-25 only.
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
