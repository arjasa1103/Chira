# Checklist

Living document. What is done, what is open, and where the evidence for each week lives.
Companion to [timeline.md](timeline.md), which tracks dates.

Tick a box when the work lands on `main` **and** something written backs it up. Every
completed week below links to its own write-up, so a claim here is always one click from
its evidence.

Last updated 2026-10-01. Source of truth for task detail stays [PLAN.md](../PLAN.md) and
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
- [x] Abbreviation map vendored in the package (`src/chira/abbr_map_collector.json`): the first real dispatch crashed because `data/` is gitignored, so Actions never had the map (2026-09-28)
- [x] Heartbeat proven end to end: run 36482495778, `heartbeat_delivered: true` (2026-09-28)
- [x] **Cron uncommented and firing** (2026-09-28). Two scheduled runs on 09-29, both green
- [x] **NHL opener 2026-09-29 captured by hand dispatch** (run 36623363003, 20:01Z): all five games every 5 minutes from pre-game through tipoff, 552 quotes across two runs
- [x] **Schedule rebuilt for the 3-6 h cron lag** (`294dcd3`, 2026-10-01): fires every 30 min at :17/:47, each run polls, waits (within 45 min) or exits without pinging; sessions end at window close and hand over through the concurrency group. Replaces the `45 1` slot that idled 5h30 and pinged success every night
- [x] Artifacts copied to `data/collector-archive/` (gitignored), 9 runs; re-run after each game night (90-day retention, runs do not accumulate). Known loss: 09-30 PIT@PHI and NYI@TOR have no T-6h or T-1h (no dispatch, scheduled run 3h23 late), not recoverable
- [ ] **The new schedule covers a night on its own.** First run on the new schedule: 36915430888, created 19:35Z 10-01, inside the 45-minute wait margin, so it waited for the 20:00Z opening and is polling tonight's slate; no hand dispatch is on record for 10-01. Tick once its artifact shows tonight's games captured from pre-game. Until then the hand dispatch stays the safety net
- [x] **Healthchecks period → 1 day, grace 6 h** (2026-10-01). Sessions now end at window close, so pings can be ~19 h apart
- [x] Heartbeat owner decided (2026-10-01): **GitHub Actions owns `CHIRA_HEARTBEAT_URL`** and the collector stays on Actions. Any other runner gets its own Healthchecks check and its own variable (Chira-gamble's runner uses `CHIRA_GAMBLE_HEARTBEAT_URL`), so one green check can never hide another dead one. Reopen only if the collector itself moves off Actions
- [ ] Wire NBA upcoming enumeration — before 2026-10-20. Source check 2026-10-01: the census's `nba_api` (stats.nba.com) needs a residential IP, so likely fails on Actions; `cdn.nba.com` schedule JSON returned 403 even locally; ESPN's scoreboard API answered locally (3 games on 10-20) but is unproven from Actions, and its 19:00Z BOS@DET looks like a placeholder time. Prove the source with a `once` dispatch before relying on it
- [x] 2026-27 abbreviation map: **the 2025-26 fallback is accepted** (2026-10-01). It resolved every listed NHL game from the opener on; the only unresolved games were `no_market` (Polymarket had not listed them yet). The fallback is safe because `confirm` checks both team labels against each market's own outcomes, so a drifted code shows up as an unresolved game, never as a wrong market. **Reopen** if any unresolved reason other than `no_market` appears, and re-check NBA once its 2026-27 markets list

Feature store half, **done 2026-09-27** → [notes/week7-features.md](../notes/week7-features.md)

- [x] Point-in-time assembly (E9), every query taking a mandatory `as_of` with no default
- [x] Leakage canary (E5), the seventh P1 test: truncation, held-but-future game, and a must-fail form, on fakes and on the real census
- [x] Features: rest days, back-to-backs, 7-day density, travel distance, time-zone shift, prior results behind `RESULT_DELAY_SECONDS`
- [x] Venue table vendored, 62 rows, pinned against ten published distances
- [x] T15, the narrow `game_prices` table: 36,976 rows, 0 disagreements with the census on six columns
- [x] No price column in the feature frame, asserted by a test
- [ ] E7: prove an availability source, timeboxed, needs live games from late October

## Weeks 8-9 — the model — **in progress: rating frozen 2026-10-01; model not started**

Before the first fit (engineering review, 2026-09-27):

- [x] Model extras installed. Use `uv sync --extra store --extra model --group dev`: `uv sync --extra model` on its own is an exact sync and **removes** matplotlib and pyarrow
- [x] PREREGISTRATION Amendment 5, written before any model code (2026-09-28): NHL back-to-back x home term; Elo rating tuned on 2024-25 only with the overlap disclosed; monthly rolling origins; missing-travel fill rule; holdout opened by code once → [PREREGISTRATION.md](../PREREGISTRATION.md)
- [x] **Brier confirmed as the primary score** in [PLAN.md](../PLAN.md) Phase 5, with the reason (2026-10-01): an unclipped log loss is unbounded, so one mis-joined label at an extreme price can move it without limit while Brier's worst single game contributes 1 — and labels come from a third party, joined by slug, where this project has already found defects. Log loss still reported for every result
- [x] NBA neutral-site list, vendored and applied inside the feature query, with regression tests; the league's own `isNeutral` is wrong for 2023-24 and is ignored → [notes/week7-neutral-and-holdout.md](../notes/week7-neutral-and-holdout.md)
- [ ] Missing travel filled with the dev median, count printed in every fit report (pre-registered in 5d; lands with the model)
- [x] Holdout seal in code: `open_holdout()` refuses a dirty tree, a second call, and an unpushed HEAD, and commits a marker; `assert_dev_only` refuses holdout rows and season-less rows (2026-09-28, hardened 2026-09-29)
- [x] **Residual seal bypass closed in code** (2026-10-01). `open_holdout` pushes the marker before returning any label, and a failed push releases nothing while leaving the marker committed locally, so the next attempt refuses. `marker_on_remote` reads `<upstream>:HOLDOUT_OPENED.json` after a fetch and `is_open` consults it; an unreachable remote **raises**, because "cannot tell" is not "not opened". Tests pin the reproduction, a fresh clone of the tip, a failed push, and an unreachable remote
- [x] **The seal's failed-push dead end, fixed in review** (2026-10-01). The first version kept the marker after a failed push and said "push it yourself, then re-run"; the re-run refused on that local marker, so one network blip spent the holdout with **no label ever released** (reproduced against the real module with an unwritable remote). Now labels are released only once the marker is **confirmed on the remote**; a push that does not land rolls the local marker commit back (`reset --keep`, never over other changes) and a retry opens cleanly; a push that lands but reports failure still releases; an unconfirmable push keeps the marker and a re-run settles it. Re-verified with the real unwritable-remote reproduction. 944 tests pass
- [x] **Branch protection on `main`: ruleset `protect-main` active** (id 24330616, 2026-10-01). It blocks deletion and force-pushes only (`deletion`, `non_fast_forward`), with no bypass list; pull requests and status checks are deliberately not required, so the seal's marker push still lands. Verified with `gh api repos/arjasa1103/Chira/rules/branches/main`. Was: **a GitHub setting, the user's.** The last link code cannot close: a force-push can still remove the pushed marker. Stated in `holdout.py`'s docstring so the seal is never read as airtight without it. **Block force-pushes and deletions only; do NOT require pull requests or status checks on `main`**, because `open_holdout` pushes its marker straight to `main`. A rule that rejects that push no longer spends the seal (it rolls back), but it would stop the holdout from ever opening. Checked 2026-10-01: `main` is not yet protected
- [x] Seal scope written down (`334b09c`, 2026-10-01): pre-game inputs from EARLIER 2025-26 results (feature win rates, the 2025-26 Elo walk) are features guarded by the two canaries; the seal guards scoring → [notes/week7-neutral-and-holdout.md](../notes/week7-neutral-and-holdout.md)
- [x] **Home advantage decided and recorded as the third reading of 5b** (2026-10-01). The model takes `ratings.MODEL_COVARIATE` (`rating_diff_strength`, H excluded) and owns home advantage entirely; `rating_diff` keeps the bonus only for `p_home_elo`, which the grid was tuned on. `H × 1[not neutral]` is constant across **2,531 of 2,542 dev games** — 2024-25 has only 11 neutral-site games — so carrying H into the covariate is collinear with the model's own home term on 99.57% of the sample. Pre-stated consequence: the neutral adjustment is identified by 11 games and will be reported as shrunk toward its prior

**Left for week 8, in order** (handed to the dev agent 2026-10-01) — **items 1-5 done 2026-10-01**:

1. [x] Review fixes and the seal-scope note committed (`334b09c`)
2. [x] Home-advantage decision, recorded as the third reading of 5b (`0a75bc0`)
3. [x] Brier-primary decision in PLAN.md, with the reason (`0a75bc0`)
4. [x] Residual seal bypass closed, plus its tests (`0a75bc0`). Branch protection is the user's
5. [x] TODOS: seal bypass recorded and resolved; NHL back-to-back closed on Amendment 5a; heartbeat-owner P1 closed on the 2026-10-01 decision (`0a75bc0`)
6. [x] **Pushed** 2026-10-01, with the review's seal fix, after a review of the four commits (944 tests pass, lint clean)

The model:

- [x] **Deterministic pre-game rating, frozen** (`d66671c`, 2026-10-01, pushed the same day): NBA K=20 H=50 c=0.6 (log loss 0.60781), NHL K=16 H=50 c=0.9 (0.66618); both optima on a grid edge, disclosed, not widened; all 245 grid points published → [notes/week8-ratings.md](../notes/week8-ratings.md)
- [x] 2023-24 burn-in fetched in full (1,230 NBA, 1,312 NHL), Arizona carried into Utah
- [x] Review fixes (`334b09c`, 2026-10-01): delay override honoured; frozen values pinned by a CI golden test and a real-data recompute; the rating's own point-in-time canary with a must-fail form; NBA neutral override moved inside the walk. 928 tests pass
- [x] **Freeze pushed** (`d66671c` on `origin/main`, 2026-10-01), before any 2025-26 rating was computed
- [ ] 2025-26 ratings computed with the frozen constants, unchanged
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
- [ ] With v2, update v1's prior-art line in `docs/index.md`: it still says SSRN 5910522 was "blocked to automated access"; it was read by hand 2026-10-01 and the contribution stands (decided 2026-10-01: v1 stays as published until v2)

---

## Open items that are not week-shaped

Detail and reasoning live in [TODOS.md](../TODOS.md).

| Priority | Item | Deadline |
|---|---|---|
| P1 | Hand-dispatch the collector each game night, 19:55Z (16:55 ADT), until the new schedule covers a night alone. 10-01: the schedule's own run is covering it; confirm from the artifact | Until confirmed |
| P1 | NBA upcoming enumeration for the collector | **2026-10-20** |
| P2 | Wilkens (2026) citation unverified (SSRN 5910522 read 2026-10-01: contribution stands) | Before v2 |
| P3 | Verify `last_trade_price` is market-level before anything reads it | Unscheduled |
| P2 | Cache sizing, store hardening, test-fixture consolidation | Unscheduled |
| P3 | CI actions on deprecated Node 20; Ubuntu 26 migration | 2026-10-19 |
| P3 | T16 census cross-validation, E19 special-game routing | Unscheduled |

## Standing rules that are not tasks

- The **2025-26 season is sealed** until the model is frozen. It gets one pass. The seal
  guards scoring; inputs built from earlier results are features, guarded by the canaries.
- **Nothing availability-derived** enters the historical feature set.
- The **market price is banned** from the headline model; it exists only for the nested test.
- Every published number is rounded **from `headline2.json`**, never from a note's
  intermediate value.
