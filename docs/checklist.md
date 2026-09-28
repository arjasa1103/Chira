# Checklist

Living document. What is done, what is open, and where the evidence for each week lives.
Companion to [timeline.md](timeline.md), which tracks dates.

Tick a box when the work lands on `main` **and** something written backs it up. Every
completed week below links to its own write-up, so a claim here is always one click from
its evidence.

Last updated 2026-09-27. Source of truth for task detail stays [PLAN.md](../PLAN.md) and
[TODOS.md](../TODOS.md); this page is the index over them.

---

## Week 1 — foundations — **done 2026-09-11**

- [x] Rate-limit calibration probe → [notes/week1-rate-limit.md](../notes/week1-rate-limit.md)
- [x] Slug conventions and the ET/UTC date discovery → [notes/week1-slug-conventions.md](../notes/week1-slug-conventions.md)
- [x] Per-season abbreviation maps learned
- [x] Noise-floor simulation at per-stratum n
- [x] `PREREGISTRATION.md` committed last → [PREREGISTRATION.md](../PREREGISTRATION.md)
- [x] Polymarket ToS question opened → [notes/week1-tos-check.md](../notes/week1-tos-check.md)

## Week 2 — the pipeline and its gate — **done 2026-09-12**

- [x] HTTP layer, cache hardening, circuit breaker
- [x] DuckDB store, misses table, reconciliation identity
- [x] Census runner, idempotent and resumable
- [x] Abbreviation resolution, 124/124 team-seasons → [notes/week2-abbr-resolution.md](../notes/week2-abbr-resolution.md)
- [x] NHL schedule source named and probed → [notes/week2-nhl-schedule.md](../notes/week2-nhl-schedule.md)
- [x] Validation gate passing on all four sport-seasons → [notes/week2-census-gate.md](../notes/week2-census-gate.md)

## Week 3 — the census — **done 2026-09-13**

- [x] Full census: 5,084 scheduled, 4,661 priced, 423 classified misses
- [x] Immutable Parquet snapshot, `census-20260913-224d6ad985e0`
- [x] Amendment 1: the close cuts at the league's tipoff, not Gamma's
- [x] Three defects found and fixed (spread markets, tipoff times, complementarity)
- [x] Write-up → [notes/week3-census.md](../notes/week3-census.md)

## Week 4 — the two gate charts — **done 2026-09-16**

- [x] Chart 1, coverage by week of season → [charts/chart1-coverage.png](charts/chart1-coverage.png)
- [x] Chart 2, the market's own calibration → [charts/chart2-calibration.png](charts/chart2-calibration.png)
- [x] Primary sport decided: NBA
- [x] Synthetic scorer (T10)
- [x] Amendment 2: the Cox slope band re-derived from the real pool
- [x] Forward collector built, dead-man's switch provider-pluggable
- [x] Write-up → [notes/week4-charts.md](../notes/week4-charts.md)

## Week 5 — headline 2 — **done 2026-09-21**

- [x] The 2×2 strata, cut within phase (Amendment 3a)
- [x] Primary test: slope difference +0.812, 95% CI [+0.618, +1.033]
- [x] NHL reported as contrast case (Amendment 3b)
- [x] Volume proxy withdrawn on measurement (Amendment 4)
- [x] Every robustness split, including the price-range artifact checks
- [x] Chart 3 → [charts/chart3-headline2.png](charts/chart3-headline2.png)
- [x] Write-up → [notes/week5-headline2.md](../notes/week5-headline2.md)

## Week 6 — artifact v1 — **done 2026-09-25**

- [x] The writeup, published → [index.md](index.md) (live at [arjasa1103.github.io/Chira](https://arjasa1103.github.io/Chira/))
- [x] Prior art, four sources, one contradicting the plan → [prior-art.md](prior-art.md)
- [x] Reproduction path replacing the dataset release (`scripts/reproduce.py`)
- [x] GitHub Pages live, serving from `main` `/docs`
- [x] Licences: MIT for code, CC BY 4.0 for the writeup
- [x] E18 resolved: no dataset release → [notes/week1-tos-check.md](../notes/week1-tos-check.md)
- [x] Published on 6 of 7 P1 tests, stated in the artifact's own limitations

## Week 7 — collector and feature store — **done 2026-09-27** (E7 date-locked)

Collector half, **done 2026-09-26** → [notes/week7-collector.md](../notes/week7-collector.md)

- [x] Live polling path wired (`src/chira/upcoming.py`, `resolve_targets`, `poll_target`)
- [x] Rehearsed against live markets: 47 of 47 resolved, 36 rows captured
- [x] NHL season window fixed: opened 2026-10-01, league opens 2026-09-29
- [x] `--check-windows` verifies every window against the real schedule
- [x] Zero-capture rule takes the denominator, so a quiet night is not an outage
- [ ] **Uncomment the cron** in `.github/workflows/collector.yml` — **before 2026-09-29**
- [ ] If the collector runs off Actions: export `CHIRA_HEARTBEAT_URL` there, one heartbeat owner (P1 in TODOS)
- [ ] Wire NBA upcoming enumeration — before 2026-10-20
- [ ] Resolve a 2026-27 abbreviation map (the 2025-26 map is a logged fallback)

Feature store half, **done 2026-09-27** → [notes/week7-features.md](../notes/week7-features.md)

- [x] Point-in-time assembly (E9), every query taking a mandatory `as_of` with no default
- [x] Leakage canary (E5), the seventh P1 test: truncation, held-but-future game, and a must-fail form, on fakes and on the real census
- [x] Features: rest days, back-to-backs, 7-day density, travel distance, time-zone shift, prior results behind `RESULT_DELAY_SECONDS`
- [x] Venue table vendored, 62 rows, pinned against ten published distances
- [x] T15, the narrow `game_prices` table: 36,976 rows, 0 disagreements with the census on six columns
- [x] No price column in the feature frame, asserted by a test
- [ ] E7: prove an availability source, timeboxed, needs live games from late October

## Weeks 8-9 — the model — **not started; spec decided 2026-09-27**

Before the first fit (engineering review, 2026-09-27):

- [ ] `uv sync --extra model` (numpyro and jax are declared but not installed)
- [ ] PREREGISTRATION Amendment 5: NHL back-to-back x home term; rating grid (K, home bonus, season carry-over) tuned on 2024-25 only, then frozen; all teams start at 1500; monthly rolling origins
- [ ] Brier confirmed as the primary score in PLAN.md, with the reason; log loss still reported
- [ ] NBA neutral-site list, applied inside the feature query (the census store stays untouched), with regression tests
- [ ] Missing travel filled with the dev median, count printed in every fit report
- [ ] Holdout guard in code: fitting on 2025-26 raises; `open_holdout()` runs once and writes a marker

The model:

- [ ] Deterministic pre-game rating module, JAX-free, with its own point-in-time canary
- [ ] Hierarchical logistic in `numpyro`, deterministic pre-game ratings as a fixed covariate
- [ ] MCMC diagnostics as hard failures (T5)
- [ ] Hyperprior sensitivity analysis
- [ ] GBM fitted as a reported benchmark ceiling (T17)
- [ ] Full dress rehearsal on 2024-25, producing every table and figure
- [ ] **The 2025-26 holdout opened exactly once**, after the model is frozen by commit
- [ ] Nested test: Clark-West against both nulls, under both closing-price constructions

## Weeks 10-11 — artifact v2 — **not started**

- [ ] Headline 1: model Brier and log loss beside the market's
- [ ] Risk tiers reported with game-level bootstrap intervals
- [ ] Artifact v2 published

---

## Open items that are not week-shaped

Detail and reasoning live in [TODOS.md](../TODOS.md).

| Priority | Item | Deadline |
|---|---|---|
| P1 | Uncomment the collector cron | 2026-09-29 |
| P1 | Heartbeat owner if the collector runs off Actions | Before the first off-Actions run |
| P1 | SSRN 5910522 unverified (403 to automated access; needs a human) | Before v2 |
| P2 | NBA `neutral_site` has no source (decided: vendored overlay) | Before the first fit |
| P2 | NHL back-to-back is partly a road dummy (decided: interaction term) | Before the first fit |
| P2 | Wheatcroft ranks the log score above Brier (decided: keep Brier, write the reason) | Before the first fit |
| P3 | Verify `last_trade_price` is market-level before anything reads it | Unscheduled |
| P2 | Cache sizing, store hardening, test-fixture consolidation | Unscheduled |
| P3 | CI actions on deprecated Node 20; Ubuntu 26 migration | 2026-10-19 |
| P3 | T16 census cross-validation, E19 special-game routing | Unscheduled |

## Standing rules that are not tasks

- The **2025-26 season is sealed** until the model is frozen. It gets one pass.
- **Nothing availability-derived** enters the historical feature set.
- The **market price is banned** from the headline model; it exists only for the nested test.
- Every published number is rounded **from `headline2.json`**, never from a note's
  intermediate value.
