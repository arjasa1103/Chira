<!-- /autoplan restore point: /Users/arva/.gstack/projects/Chira/main-autoplan-restore-20260911-160417.md -->
# Chira — Implementation Plan

Branch: main
Design doc: [docs/designs/chira-market-calibration-engine.md](docs/designs/chira-market-calibration-engine.md)
Status: **APPROVED** 2026-09-11 (autoplan: CEO + Eng + Eng re-review). All decisions closed.
**HARD DEADLINE: end of November 2026.** Semester project. ~11 weeks from 2026-09-11.

## Deadline, and what that excludes

**End of November 2026 is a hard deadline.** This is a semester project whose purpose is to
learn data mining and ML. Both a **model** and a **publishable artifact** must land before
December. The startup/product path is explicitly later; the artifact may stay private as a
job-application portfolio piece.

**Phase 6 (forward capture / the availability hypothesis) is EXCLUDED from the December
deliverable, by arithmetic rather than preference.** Per sport: the NBA 2026-27 season tips
late October, giving **~5 weeks** of forward data by end of November; the NHL season starts
earlier in October, giving **~8 weeks**. Both fall far short of a 200-400 status-change game
minimum-n gate, so the conclusion holds for each sport independently.

**Note this retires the original justification for the second sport.** NHL was chosen partly
because the late-announced starting goalie was a cleaner version of the late-news edge
hypothesis. With availability dropped from the December deliverable, **NHL is now justified
by headline 2's per-stratum n instead.** That makes NHL load-bearing for the co-headline, so
it is NOT the right thing to cut if week 3 runs long. The collector still runs from
late October so the 2027 option stays open, but its results are a follow-up post and are
not part of what ships this semester.

**Amended 2026-09-20 (PREREGISTRATION.md Amendment 3b).** The per-stratum-n argument held;
n was never the problem. What it could not anticipate is that the NHL market carries almost
no information (Murphy resolution 0.0152 and 0.0057, against NBA's 0.0483 and 0.0520), and a
market quoting near the base rate cannot be shown to be miscalibrated in an interesting way
at any n. NHL is therefore the **contrast case**, and the headline-2 primary directional test
runs on NBA. NHL is still collected, analysed and published in full, so nothing is cut.

### Eleven-week schedule

**STAGE THE DELIVERABLE, NOT THE WORK.** The original schedule put the entire artifact in
weeks 10-11, behind nine consecutive weeks of critical path with no float. Any slip in weeks
1-9 would not have delayed December, it would have **deleted the artifact**, because the
model cannot be dropped once the holdout is opened but a writeup can always be "finished
later." Corrected: headline 2 ships as a complete, frozen, publishable artifact at the end of
week 6. Weeks 7-11 then ADD headline 1 as a second section to a document that already exists
and is already shippable. This keeps Approach B and cuts nothing; it converts
"ship or nothing" into "ship more or ship less."

| Weeks | Work | Gate |
|---|---|---|
| 1 (Sep 15-21) | Rate-limit probe, per-season abbr maps, **the modeling pre-commit (see A4)**, noise-floor simulation **run at per-stratum n**, Polymarket **ToS check** (20 min), then `PREREGISTRATION.md` | Pre-registration committed LAST |
| 2 (Sep 22-28) | `uv` skeleton, HTTP layer + cache hardening, misses table, idempotency, telemetry, NHL endpoint named/probed/vendored. **Census validation gate on the first 200 games**: label agreement, complementarity, reconciliation fault-injection, shuffled-join | Gate passes BEFORE the full pull |
| 3 (Sep 29-Oct 5) | Full census both sports (~15,300 requests), immutable snapshot release | `scheduled == priced + misses` balances |
| 4 (Oct 6-12) | Charts 1 and 2, synthetic scorer. **Prices-only collector** + dead-man's switch + dry run | Coverage chart decides primary sport |
| 5-6 (Oct 13-26) | Headline-2 analysis (T9), the 7 designated P1 tests, **then WRITE, PUBLISH AND FREEZE the artifact v1**: headline 2 + dataset release + prior-art section + GitHub Pages | **An artifact exists and is public** |

**Week 5 status (2026-09-21).** T9 is done and the primary test returns a positive,
robust result (see T9 below and notes/week5-headline2.md). Of the 7 designated P1 tests, 6
are covered; **the leakage canary is not, and cannot be yet** -- it guards the feature
store's point-in-time `as_of` machinery, which is Phase 3 in week 7, so it is scheduled
there rather than counted as done. Week 6 remains: the writeup, the dataset release (still
**rescoped, see below**), the prior-art section, and GitHub Pages.

**Decision 2026-09-25: artifact v1 publishes on 6 of 7 P1 tests.** The week 5-6 gate row
above reads "the 7 designated P1 tests, then publish"; that is amended here rather than
quietly passed. The seventh, the leakage canary, guards `as_of` machinery that does not
exist until Phase 3 in week 7, so holding v1 for it would invert the staging logic this
schedule is built on: v1 exists precisely so a week 7-11 slip cannot delete the artifact.
The canary is scheduled in week 7 alongside the code it guards, and **artifact v1 states
the 6-of-7 position in its own limitations section** rather than leaving a reader to infer
that the test plan was complete. Heartbeat secret set the same day, so the collector's
dead-man's switch is armed ahead of its late-October window.

**E18 resolved 2026-09-22.** The user read the Terms of Use. "Data" is defined to include
derived and aggregated forms, which kills week 1's "publish aggregates only" mitigation, and
redistribution is prohibited to capital-markets entities, which a public release cannot
exclude. **Decision: no dataset release.** T11/E1 become the collector code plus a
reproduction path, which still meets the week-6 gate. Licences added: MIT for code, CC BY
4.0 for the writeup. Full reading: notes/week1-tos-check.md.
| 7 (Oct 27-Nov 2) | Feature store with `ASOF JOIN`. One timeboxed slot to prove the availability source against live regular-season games | Availability: proven or dropped |
| 8-9 (Nov 3-16) | Model, **full dress rehearsal on dev producing every table and figure**, then sealed holdout opened ONCE | Holdout opened once, never reopened |
| 10-11 (Nov 17-30) | Add headline 1 as artifact v2. Remaining tests "if time" | v2 published |

**Honest effort accounting** (the earlier "~6 hours of CC time" figure was misleading and is
corrected here):

- The 17 P1 tasks across both phases sum to **~5.8h CC / ~55h human**. That is the *review
  remediation backlog only*.
- It contains **no line for the actual build**: HTTP layer, census runner, DuckDB store,
  feature store, numpyro model, scoring module, charts, or writeup. Those live in the
  Phase 0-5 bodies and are **unestimated**.
- **Capacity assumption: ~15 human hours/week** alongside coursework. Week 1 alone is
  realistically 25-35 hours, so week 1 is the second slip risk after week 4.
- **If sustained capacity proves to be under ~15h/week, the correct cut is one sport (drop
  NHL) or the model, NOT the artifact and NOT the tests.** Dropping NHL costs headline 2 its
  per-stratum n, so prefer dropping the model and shipping v1 only.

**Collector, split across two slots** (the single week-4 slot was unexecutable: proving an
availability status *change* requires regular-season injury reports, and the NBA season tips
late October, after week 4 ends Oct 12):
- **Week 4 (2026-09-16): three of the four items landed.**
  - [x] **Prices-only collector** (`src/chira/collector.py`, `scripts/run_collector.py`).
  - [x] **Dead-man's switch** — external monitor alerting on the ABSENCE of a success ping.
        Built and provider-pluggable; **not armed** until the secret is set, see below.
  - [x] **Pre-season dry run** (`--dry-run`, plus offline tests of every gate).
  - [ ] **Keepalive against the 60-day Actions auto-disable — NOT built, and probably not
        needed.** Recorded honestly rather than ticked: the 60-day clock only disables
        workflows that are *enabled and scheduled*, this repo's cron is commented out, and
        the repo takes commits weekly, so the inactivity window is never approached. A
        keepalive would also duplicate the switch above, which already catches a disabled
        workflow as silence — and a keepalive that is itself a scheduled workflow faces the
        same auto-disable it exists to prevent. Revisit when the cron is enabled; tracked in
        TODOS.md.

  The workflow is committed but **deliberately not enabled**, and the live polling path is
  code-complete but unexercised — the 2026-27 slate does not exist yet, so the week-4
  verification is the dry run plus offline tests of the gates. See notes/week4-charts.md.
- **Week 7:** one timeboxed slot to prove an availability source against live games. If it
  cannot be proven in that slot, **collect prices only and drop availability entirely.**
- **Provider chosen: Healthchecks.io** (user decision, 2026-09-16), kept swappable. It is
  purpose-built for alerting on a ping's absence, its free tier covers this project, it has
  a real failure channel, and it can be self-hosted later if depending on a third party
  becomes a problem.
  **Switching provider is an env var, not a code change:** `CHIRA_HEARTBEAT_PROVIDER`
  selects any key of `collector.HEARTBEAT_PROVIDERS`, and an unknown name raises rather
  than falling back, because a typo that pinged the wrong URL shape would leave the monitor
  green while the collector was dead.
  An earlier draft of this note claimed every provider accepts `<url>/fail`. **That was
  wrong**, and writing the registry is what exposed it: Cronitor takes state as a query
  parameter (`?state=complete|fail`), and Better Stack heartbeats have no failure path at
  all, so on failure the collector must send NOTHING — pinging would report success.
- **STILL OUTSTANDING, needs the user:** create the Healthchecks.io check and set
  `CHIRA_HEARTBEAT_URL` as a repo secret. **Until it is set the switch is not armed** and a
  collector that never starts reports nothing to nobody. Must be done before late October,
  and before the cron in `.github/workflows/collector.yml` is uncommented.

## Goal

An interpretable, cross-sport win-probability engine benchmarked against Polymarket
closing prices. NBA and NHL. The claim is calibration, not profit: how well-calibrated is
a model trained only on public schedule and team data, measured against a real-money
market that prices $1M-$2M per game.

Portfolio artifact first. The output is a published writeup with charts, not just a repo.

**Two independent headline results, not one** (User Challenge 2, accepted):

1. **Model calibration vs the closing line.** The price-free model's Brier and log loss
   beside the market's on the sealed holdout, plus the nested test. Expected outcome is a
   0.02-0.03 Brier deficit, decomposed and explained.
2. **Where the market is miscalibrated.** The market's own calibration stratified by
   liquidity, time-to-close, and early season. Published research reports no *general*
   favorite-longshot bias on Polymarket with the bias **concentrated in specific
   categories** (arXiv 2602.19520; Reichenbach & Walther, SSRN 5910522), so this question
   has a real chance of a positive answer. The two usable seasons differ 4x in per-game
   liquidity ($500k vs $1.9M), which is a natural experiment already being collected.

Result 2 is deadline insurance because it **ships first** (end of week 6) and is independent
of whether the model beats the line. Task T9 is **promoted from P2 to P1** — it is a headline
deliverable, not a nice-to-have.

**Three honest caveats on result 2, all raised by the eng re-review:**

- **It guarantees a measurement, not a finding.** A set of curves always exists. Under the
  n constraints below, the likely outcome is wide overlapping bands, which is a null with
  extra steps. It is still the best insurance available, but it is not insurance against a
  null headline.
- **Liquidity is confounded with season regime.** A low-liquidity stratum built by pooling
  seasons is mostly 2024-25 games, so "liquidity effect" and "2024-25 effect" are the same
  cut. The plan documented this confound for the model and not for this headline.
  **Stratify on within-season volume deciles** so liquidity varies at fixed regime, and
  report the between-season contrast separately as an explicitly confounded descriptive.
- **Per-stratum n is thin, in exactly the regime the plan condemned.** If ECE at n=5,084 is
  noise-dominated, per-stratum ECE at n≈850 has ~2.4x the standard error. And ten
  equal-count bins at ~85 games/bin gives SE ≈ 0.054, while NBA/NHL moneylines concentrate
  in roughly 0.35-0.80, so the tail bins where the literature reports bias hold a handful of
  games each. **The week-1 noise-floor simulation must be run at per-stratum n, and the
  minimum n per stratum pre-registered from it, before the strata are chosen.**
- **Volume is terminal cumulative volume**, which is outcome-correlated (close games attract
  volume) and mutable. Conditioning calibration on it is selection on a variable correlated
  with outcome uncertainty. State the definition in the pre-registration and report the
  caveat.
- **Family-wise policy is mandatory here.** With ~24 strata cells an uncorrected sweep
  produces a "finding" by construction. One primary directional test; everything else
  exploratory.

## Non-negotiable constraints

- **Interpretability vetoes model classes.** Additive and legible only. A gradient-boosted
  ensemble at 0.18 Brier fails this spec; a hierarchical logistic at 0.20 passes it.
- **The market price is banned from the headline model** and required only for the nested
  test's Model B. Separate code paths, price physically absent from the standalone feature
  table.
- **Moneyline only.** Spreads and totals out of scope.
- **Pre-registration is committed before the first model fit.** The git hash is the
  timestamp.

## Week 2 — what shipped (Sep 22-28, done 2026-09-12)

Modules: `cache.py`, `store.py` + `schema.sql`, `telemetry.py`, `census.py`, `gate.py`,
`nhl.py`, `resolve.py`. Scripts: `resolve_abbrs.py`, `run_census.py`,
`probe_nhl_schedule.py`. Tests: 252 passing.

- **NHL schedule source named and probed (E10).**
  `api-web.nhle.com/v1/club-schedule-season/{TEAM}/{SEASONCODE}`, 64 calls for both
  seasons, 1,312 regular-season games each (2,624 total, matching the plan's estimate),
  final scores present so the winner is independent of Polymarket, and zero ties across
  all 2,624. Cloud egress is NOT verified; that is the week-4 dry run.
- **Abbreviation resolution (T3 completed).** 124/124 team-seasons, 91 probes. Found
  `vgk -> las`, which no document had.
- **Misses table with an 11-value reason enum and the full attempted-slug list (T2).**
- **Idempotency and resume (T6, E20).** Primary keys plus `INSERT OR REPLACE`; resume
  equality is a canonical content digest with float tolerance, excluding run metadata.
- **Cache hardening (E6).** Schema validation before any write; empty payloads never
  cached; cache key versioned by the abbreviation-map fingerprint; every `no_market`
  re-probed once with the cache bypassed.
- **Telemetry (T13).** One flushed JSONL line per game plus a manifest carrying the git
  hash, date window and map fingerprint.
- **The census validation gate PASSES on all four sport-seasons**, on 200-game stride
  slices. 800 games attempted, **735 priced, 735/735 label agreement, zero
  disagreements**, complementarity clean on all 735, and the clobTokenIds leg of the
  orientation chain independently verified in every sport-season.

| Sport | Season | Attempted | Priced | Label agreement | `et` / `et_plus_1` | Discrimination |
|---|---|---|---|---|---|---|
| NBA | 2024-25 | 200 | 200 (100%) | 200/200 | 200 / 0 | 5.9σ |
| NHL | 2024-25 | 200 | 136 (68%) | 136/136 | 136 / 0 | 2.7σ |
| NBA | 2025-26 | 200 | 199 (99.5%) | 199/199 | 184 / 15 | 7.6σ |
| NHL | 2025-26 | 200 | 200 (100%) | 200/200 | 189 / 11 | 3.0σ |

  The first version of this table reported 960 priced and NHL 2024-25 at 40%. Two
  slices were contaminated by pre-fix runs (one censused the season's last 200 games,
  one its first 200) and were discarded and re-run; see notes/week2-census-gate.md.

Five findings that change later phases:

1. **Polymarket's NHL coverage starts in December 2024.** Every attempted
   October-November game returned `no_market` and every one survived a cache-bypassed
   re-probe, on both the contaminated and the clean sample. The early-season stratum
   for headline 2 does not exist for NHL 2024-25, and NHL's usable 2024-25 n is
   roughly 1,000, not 1,312.
2. **The second date convention is load-bearing, and only in 2025-26.** 26 of 960 games
   hit via `et_plus_1` and would otherwise have been booked `no_market`; zero of 561
   games in 2024-25 needed it. **Correction to week 1:** the upstream slug bug was
   thought "fixed around late November 2025", but all 11 NHL hits are in December 2025,
   so the change is not simultaneous across sports.
3. **Measured liquidity, and it is not what the plan assumed.** Median terminal volume:
   NBA $313k (2024-25) -> $1.88M (2025-26); NHL $58k -> $614k. The 2025-26 NBA figure
   confirms the plan's ~$1.9M, but 2024-25 measures $313k rather than the assumed
   ~$500k, so the between-season contrast is LARGER than planned. NHL is ~5x thinner
   than NBA in both seasons, which means pooling sports would make "liquidity" and
   "sport" the same cut, on top of the documented liquidity/season-regime confound.
4. **`schedule.nba_games` was unsorted.** `LeagueGameFinder` returns newest first, so
   `--limit 200` censused the LAST 200 games of the season while the flag said earliest.
   Both schedule sources now return `(et_date, game_id)` order, and limited runs default
   to a stride slice across the season.
5. **The last quote lands closer to tipoff in 2025-26** (mean 43s vs 56s). A property of
   the closing-price construction, better recorded now than discovered in week 9.
6. **NHL's price discriminates ~3x more weakly than NBA's** (mean p_home_close gap
   between home wins and away wins: NHL 0.04-0.06, NBA 0.16-0.21). A real property of
   the sport, and an input to the primary-sport decision in week 4.

## Week 3 — full census and snapshot (done 2026-09-13)

Prep that landed before the ~13,700-request pull (commit 625fc83):

- **A week-2 gap closed: T-6h and T-24h.** PREREGISTRATION.md section 8 treats close,
  T-1h, T-6h and T-24h as four looks at one sample, and Phase 1 below lists all four,
  but week 2 extracted only close and T-1h. Caught while planning the snapshot, not by
  any test or review.
- **The raw minute series is stored, per F10.** New `price_points` table (both tokens,
  pre- and post-tipoff), written in the same transaction as the priced row. No primary
  key at ~120M rows; measured ~20 ms per series to insert and 2.7 ms to delete one game
  from 4M rows.
- **Snapshot (T7, E13).** `snapshot.py` refuses an unfinished census, writes atomically,
  names the directory by store digest, checksums every file, is read-only on disk,
  partitions by sport/season, writes timestamps as UTC text, and freezes the volume
  definition. It is the LOCAL immutable input for weeks 4+, gitignored under `data/`
  under `data/` (E18 resolved: there is no public dataset release, see T11).
- **Fresh store.** The week-2 slices were moved to `data/census-week2-slices.duckdb`
  so every row in the week-3 store carries a week-3 `run_id`. Their payloads are all
  cached, so the 800 previously-attempted games cost almost nothing to redo.

**Result: the gate passes all seven checks on all four sport-seasons.** 5,084 games settled:
4,661 priced, 423 classified misses (421 `no_market`, 2 `no_pre_tipoff_points`), 145.6M raw
price rows. The snapshot is `data/snapshots/census-20260913-224d6ad985e0/` (162 MB, store
digest `224d6ad9...`, cut from `1013d72`). Full write-up: notes/week3-census.md.

| Sport | Season | Priced | Misses | Coverage | Median volume |
|---|---|---|---|---|---|
| NBA | 2024-25 | 1,229 | 1 | 99.9% | $296k |
| NHL | 2024-25 | 896 | 416 | 68.3% | $56k |
| NBA | 2025-26 | 1,226 | 4 | 99.7% | $2.03M |
| NHL | 2025-26 | 1,310 | 2 | 99.8% | $604k |

It took four passes, because the first failing gate exposed real defects:

1. **Spread markets priced as moneylines.** 5 NHL 2025-26 spreads passed every check; 2 more
   were caught only because the favourite won by one goal. Now selected by `sportsMarketType`.
2. **Gamma's `gameStartTime` is unreliable as the cutoff.** Off by >15 min on 76 priced games,
   up to 360 min late (in-game prices leaking into the close) and 41 NHL games exactly 4-5 h
   early. The close is now cut at the league's own start time: **PREREGISTRATION.md
   Amendment 1**, with the original-definition close kept per row (it differs on 65 games).
3. **The complementarity check compared quotes from different moments.** Now judged on
   simultaneous quote pairs, with thresholds set from the census's own measured minimums.
4. **Operational:** a sleeping laptop killed two runs (the census now waits out a lost
   network), and the first snapshot cut filled the disk with a 6 GB sort spill (price rows are
   now written unsorted).

Constraints this puts on later weeks: T-24h is missing on 100 NBA and 33 NHL 2024-25 games
(markets opened less than a day before tipoff), so the time-to-close stratum is unbalanced
across seasons; and stale closes run 31-52%, so the staleness sensitivity split matters more
than planned.

## Phase 0 — Foundations

**Scheduling note.** This checklist is not a week-1 list. The eleven-week table above
is the authority on WHEN each item lands: the `uv` skeleton and the HTTP layer are
**week-2** work, and only the rate-limit probe, the abbreviation maps, the noise-floor
simulation, the ToS check and `PREREGISTRATION.md` were week 1. The two used to
contradict each other.

- [x] `uv` project, Python 3.12 (week 2). Dependencies: `requests`, `duckdb`, `numpy`,
      `scipy`, `nba_api`; `pyarrow`/`matplotlib` behind the `store` extra and
      `numpyro`/`jax` behind `model`, so weeks 1-7 do not install a model stack.
- [x] HTTP layer (week 2): on-disk response cache (`cache.py`), rate limiter at 5 rps
      from the week-1 probe, exponential backoff with RFC 9110 `Retry-After` parsing,
      circuit breaker, and schema validation before anything is cached. Resumability is
      in the store, not the client: `census.run_census` skips games already settled.
- [x] **ORDERING (corrected by eng review, honoured in week 1):** the Phase 4 modeling decision and the
      noise-floor simulation are strict PREDECESSORS of the pre-registration.
      `PREREGISTRATION.md` is the **LAST** artifact of Phase 0, not the first. A
      pre-registration committed before the decisions that determine its contents, then
      amended, is worth nothing — and the git hash makes the amendment permanent.
- [x] Rate-limit calibration probe (done week 1; no 429 at any rate tested, see
      notes/week1-rate-limit.md): ramp until the first 429, record reset
      behaviour. A blind fixed delay is the difference between a 4-hour and a 3-day census.
- [x] `PREREGISTRATION.md` committed LAST (week 1, commit `9f3c195`; amended three times
      since, each with its own hash). Contents fixed in the design doc: sealed holdout,
      Brier primary with log loss clipped to [0.01, 0.99], one designated primary test,
      home-side-only calibration convention, Clark-West with date-block bootstrap, the
      numeric integrity gate, risk tiers at [0.02,0.05)/[0.05,0.10)/>=0.10, dev-side
      rolling-origin protocol, two closing-price constructions.
- [x] **Done week 1, re-derived against the real pool in week 4 (Amendment 2):** the
      integrity thresholds were re-derived against the
      estimator's noise floor by simulation. See Reviewer Concerns in the design doc. The
      currently written ECE and per-bin tilt caps sit at or below sampling noise and would
      fail a working pipeline.

## Phase 1 — Coverage census (the project gate)

Answers whether the project is viable, and in which sport.

- [x] Learn the abbreviation map first, **PER SEASON** — the convention is not stable
      across seasons (`nba-lal-no-2023-12-07` uses `no` for New Orleans where 2025 uses
      `nop`). Do NOT guess; confirm every mapping against the market's own `outcomes`.
      **DONE week 2:** 124/124 team-seasons resolved in 91 `/events?slug=` probes
      (`resolve.py` -> `data/abbr_map_resolved.json`). The week-1 map was the wrong
      direction (`{slug_abbr: nickname}`) and was read by no code; it is now only a prior.
      NBA needs no translation at all. NHL needs seven, identical in both seasons:
      `cgy->cal`, `mtl->mon`, `njd->nj`, `sjs->sj`, `tbl->tb`, `uta->utah`, and
      **`vgk->las`, which appears in no document and is worth 164 games**.
      See notes/week2-abbr-resolution.md.
- [x] Build slugs `<sport>-<away>-<home>-<YYYY-MM-DD>` from **US-Eastern schedule dates**
      taken directly from `nba_api` `GAME_DATE` and the NHL schedule's `gameDate`. Never
      derive ET from `gameStartTime`. **DONE week 2** (`schedule.slug_candidates`, both
      date conventions). NHL's `gameDate` was verified to be the ET date against a game
      that starts at 03:00Z, where the UTC and ET dates differ.
- [x] Enumerate from the schedule, never by paginating Gamma — DONE. `/markets` caps `limit` at
      100 and returns nothing past `offset ~2100`.
- [x] **Seasons 2024-25 and 2025-26 ONLY** (two seasons). 2023-24 is EXCLUDED: probed Dec-2023
      NBA markets carry $6/$0/$0/$0 volume and Mar-2024 has zero sports slugs, so those
      prices are not calibrated probabilities. **Do not "fix" the missing season later.**
      ~2,460 NBA games and ~2,624 NHL games. Per game: 1 `/events?slug=` + 2
      `prices-history` = 3 requests, so **~7,400 NBA + ~7,900 NHL ≈ 15,300 requests**,
      plus ~400 abbreviation-map probes.
- [ ] **Report the two seasons separately as well as pooled.** Per-game liquidity quadrupled
      between them (~$500k in 2024-25 vs ~$1.9M in 2025-26), so they are two different market
      regimes and price sharpness is not constant across them.
- [x] (week 3; the close is cut at league tipoff per Amendment 1) Per game, store `outcomePrices` (free label), `gameStartTime`, volume, and the
      minute-level series via `prices-history?market=<tokenId>&startTs=<unix>&fidelity=1`.
      Extract close, T-1h, T-6h, T-24h.
- [x] Assert `abs(p_home + p_away - 1) < 1e-6` and fail loudly — DONE; a failure routes
      the game to `misses` with reason `complementarity_failed`, and an absent away
      series is recorded as unchecked rather than silently passed. The complementarity
      invariant is verified on 3 games and load-bearing enough to be enforced.
- [x] Classify every miss as "no market exists" vs "slug variant not tried" — DONE.
      Every miss row carries the full attempted-slug list and one of 11 enum reasons,
      and every `no_market` is re-probed once with the cache bypassed before it is
      believed. Exclude
      `["0.5","0.5"]`, unresolved, and UMA-disputed markets from scoring and count them on
      a reconciliation line.

## Phase 2 — The two gate charts (done 2026-09-16, week 4)

Both charts are cut from the immutable snapshot (`docs/charts/`, with the JSON behind them
in `chart-data.json`). Full write-up: notes/week4-charts.md.

- [x] **Chart 1: coverage by week of season**, stacked with/without market, per sport, plus
      a median-volume panel. Decides whether the project proceeds and which sport is
      primary. **Done.** The NHL 2024-25 gap is the whole coverage story in one panel:
      weeks 1-8 have no markets at all (0/19 in week 1), and coverage starts at week 9.
      Everything else runs 99.7-99.9%. New finding: **median volume climbs steeply WITHIN
      every season** (NBA 2024-25 ~$50k in week 1 to ~$400k by week 18), which means volume
      decile and season phase are correlated and the section-8 2x2 is not orthogonal.
- [x] **Chart 2: the market's own calibration curve.** Home side only, one observation per
      game, equal-count or LOESS bins with bootstrap bands, Murphy decomposition of Brier
      into reliability, resolution and uncertainty.
      **This is a REPORTED RESULT, not a gate** (corrected by eng review). The earlier
      framing — "if the market is not near-calibrated, the pipeline is broken" — is an
      invalid inference, because a miscalibrated result is ambiguous between a bug and the
      Approach C headline finding, and the literature says bias IS concentrated in specific
      categories. Pipeline validity is established instead by tests that do not assume the
      market is calibrated: label agreement vs nba_api, complementarity, reconciliation,
      shuffled-join collapse, and the synthetic scorer.
      **Done.** No sport-season shows detectable miscalibration at the close: every ECE sits
      well inside its own per-n noise floor (e.g. NBA 2025-26 ECE 0.0241 against a null p99
      of 0.0515). The real signal is in the Murphy decomposition, not in reliability:
      **resolution is 0.0517 for NBA 2025-26 against 0.0055 for NHL 2025-26**, so the NHL
      market barely improves on the base rate (Brier 0.2446 vs uncertainty 0.2495).
      The one marginal result is NHL 2024-25's Cox intercept, +0.1475 with CI
      [+0.0049, +0.2881], which excludes zero but is exploratory under the section-7
      family-wise policy and sits only just outside its null CI of [-0.1482, +0.1363].
- [x] **Write the one-paragraph answer: which sport is the better primary, and why.**

> **NBA is the primary sport.** It wins on all three axes that matter and loses on none.
> **Coverage:** 99.9% and 99.7% across the two seasons against NHL's 68.3% and 99.8%, and
> the NHL shortfall is not random attrition but a contiguous eight-week hole at the start of
> 2024-25 that no re-probe can fill, so NHL's usable history is effectively 1.5 seasons to
> NBA's 2. **Market informativeness:** NBA resolution is 0.0481 and 0.0517 against NHL's
> 0.0147 and 0.0055; an NHL 2025-26 closing price improves on "always predict the home
> team" by 0.005 Brier, which is close to no information at all. **Usable price range:** NBA
> closes span 0.045-0.980 with only 40.5% inside [0.35, 0.65], while NHL spans 0.200-0.825
> with 82.6% inside it, so NHL has almost no favourites or longshots — exactly the tail
> where the literature puts the bias headline 2 is hunting, and exactly what a calibration
> curve needs in order to have shape. **NHL is still retained**, per the deadline section
> above: it is load-bearing for headline 2's per-stratum n and dropping it is not the right
> cut. But its near-zero resolution is a new risk to that role, because a market carrying
> almost no information cannot be shown to be miscalibrated in an interesting way, and that
> risk should be re-checked before the week 5-6 strata are built.
>
> **Re-checked and settled 2026-09-20 (Amendment 3b): NHL is the contrast case.** The
> primary directional test runs on NBA; NHL is reported in full as the case where a market
> is perfectly calibrated and nearly uninformative.

## Phase 3 — Ingestion and feature store

- [ ] DuckDB store. Game key: `nba_api` `GAME_ID` joined to Polymarket `conditionId` via
      an explicit, auditable join table keyed on (sport, ET date, away abbr, home abbr).
- [ ] Price table grain: one row per token per minute. **~94.6M rows** (5,084 games x 2
      tokens x ~9,300 points). Earlier drafts said 46M/69M by counting one token; corrected.
      **Partition the Parquet release by sport and season** — GitHub caps a single release
      asset at 2GB.
- [ ] **Point-in-time correctness enforced structurally.** Every feature query takes a
      mandatory `as_of`; no unqualified read path exists in the API. Regression test: a
      query with `as_of=T` returns byte-identical results against a DB truncated at T and
      a DB holding all later rows.
- [ ] Features, historical half: schedule, rest days, back-to-backs, travel distance,
      prior-game results with known completion times. **Nothing availability-derived** —
      see the blocker.

## Phase 4 — Model

> **A4 PRE-COMMIT (week 1, and it goes in `PREREGISTRATION.md`): deterministic pre-game
> ratings entering the hierarchical logistic as a FIXED COVARIATE.** "Elo-like" and
> "state-space" are two different cost classes: a deterministic Elo computed outside the
> model is free, while a latent walk per team per game is ~75k latent variables on 5,084
> observations, with divergences that T5 converts into hard failures. One fits in the
> available weeks; one does not. Choose the deterministic version. Interpretability is
> preserved and MCMC stays cheap.
>
> **RESOLVED by the eng review — adopt (a), a rolling pre-game team-strength state**
> (Elo-like / state-space) updated game by game. Sealing 2025-26 leaves one dev season, so
> the cross-season rolling-origin protocol is impossible. Option (c), team-season intercepts
> plus the "mandatory" random walk, is **arithmetically the thing it was meant to avoid**:
> with two seasons the holdout intercept is the dev intercept plus a zero-mean increment, so
> its posterior mean IS the shrunk dev estimate and only the variance changes. Option (a) is
> the only candidate that produces a holdout-season team effect from information available
> before each holdout game, and it removes the model-fit leakage path as a side effect.
> Two independent voices converged on (a). No longer a gate item.

- [ ] Hierarchical logistic in `numpyro`. Non-centered parameterization, R-hat and
      divergence diagnostics, posterior predictive checks.
- [ ] **Pool team-BY-SEASON effects** (J = 60 NBA, 64 NHL — two seasons, not three). Pool the team-season
      intercept and home advantage only. Keep rest, back-to-back and travel **global** —
      ~14 back-to-backs a season cannot support team-specific coefficients.
- [ ] **Random walk on team strength across seasons is mandatory, not optional.** The
      holdout is the most recent full season, whose team-season intercepts cannot be
      estimated from dev data. Decide and document how a holdout-season team effect is
      obtained without touching the holdout **before writing any numpyro code.**
- [ ] Hyperprior sensitivity analysis, reported. On hierarchical variance parameters the
      prior can be the result.
- [ ] Sport enters as a fixed effect.

## Phase 5 — Scoring and the nested test

- [ ] Headline: price-free model Brier and log loss beside the market's on the sealed
      holdout, reliability diagrams for both. **Pass condition: a deficit inside the
      pre-stated 0.02-0.03 Brier band, decomposed and explained.** A materially wider gap
      is a finding about the feature set.
- [ ] Nested test, sealed holdout opened once. Model A: market price. Model B: market price
      plus features. **Clark-West MSPE-adjusted statistic, not Diebold-Mariano.** Fixed
      estimation scheme, one dev estimation window, single holdout pass. Critical values by
      date-block bootstrap with the analytic normal p-value alongside.
      **Open item: ~170 date blocks is few; report the block count and consider a
      stationary bootstrap.**
- [ ] Report B against **both** nulls: the identity market price and a fitted
      recalibration `a + b*logit(p)`. Winning only against the identity null is a
      recalibration finding about a public market tilt, not private information.
- [ ] Run the nested test under **two closing-price constructions that actually differ**:
      the last pre-tipoff value, and the **T-1h value**. A gain existing only under one is
      measurement error in the benchmark.
      **A VWAP is not computable and was removed:** `prices-history` points carry only
      `{t, p}` with no volume field (verified by probe), so there are no weights; and under
      carry-forward a trailing average equals the last value on most games anyway.
- [ ] Risk tiers reported with frequency, hit rate, calibration and bootstrap intervals per
      pre-registered bucket. State expected top-tier shrinkage up front.

## Phase 6 — Forward collector (parallel, from late October 2026)

The only path to the availability hypothesis.

**Status after week 4.** The scheduling, capture-timestamp, `/midpoint` + `/book`,
external-store and cron-is-best-effort items below have LANDED in code
(`src/chira/collector.py`, `scripts/run_collector.py`,
`.github/workflows/collector.yml`, `tests/test_collector.py`), with two honest caveats:

- **Nothing has polled a live market.** The 2026-27 slate does not exist yet, so the live
  path is code-complete and unexercised. What is tested is every decision the collector
  makes *about* polling — the ET season and daily gates across the DST shift, the
  midnight-spanning window, the dedup key, the zero-capture rule, the heartbeat's
  swallow-never-raise behaviour and target selection — which is the part a live test would
  not have checked anyway. The remaining wiring is one function: resolve each upcoming game
  to its market, which reuses the census's own schedule/slug/resolve machinery.
- **The dead-man's switch is not armed** until a monitoring provider is chosen and
  `CHIRA_HEARTBEAT_URL` is set as a repo secret. See the collector note in the deadline
  section above.

Scheduling arithmetic, since it is the item most easily got wrong: the poll window is
16:00-02:30 ET, which is 20:00-06:30 UTC under EDT and 21:00-07:30 UTC under EST — a union
of about 11.5 hours. One Actions job is capped at 6 hours and a session stops at 5h30 to
leave room to report its own outcome, so **two** chained sessions cover the window. The cron
is pinned in UTC because that is all GitHub offers; the gate is computed in
`America/New_York` in code, so a DST shift moves the effective window and not the coverage.

- [ ] **Scheduling, corrected by the eng review (the earlier 5-10 minute polling was
      unaffordable: ~130 runs/day x ~180 days exceeds the free Actions allowance and the
      collector dies from quota, not from the delay the plan models).** Use **one
      long-running job per day, chained 2-3 times**, or a cheap always-on host. Pin the cron
      in **UTC with an explicit `America/New_York` conversion in code** — the season window
      and daily window are ET concepts, so a UTC cron clips the first or last game of the
      slate across DST, the same bug class already fixed for slugs. A nightly job captures nothing that deserves the name
      "closing": tipoffs are staggered and a closing snapshot must land within minutes of
      each `gameStartTime`.
- [ ] Record the **actual snapshot timestamp** on every row so staleness is measurable.
- [ ] Capture live bid/ask via `/midpoint` and `/book`, which return
      `"No orderbook exists"` for resolved markets and so are forward-only.
- [ ] Persist to an external store or release artifact. Never commit a growing DuckDB file
      into the git tree.
- [ ] GitHub Actions cron is best-effort: commonly delayed 10+ minutes, dropped under load,
      auto-disabled after 60 days of repo inactivity. Treat delay as measured, not assumed
      away.
- [ ] **Pre-register the availability test in a SEPARATE, LATER-HASHED ADDENDUM**, committed
      only once the source is proven in week 7. It must not sit in the week-1
      `PREREGISTRATION.md`, because week 1 would be pre-registering a test whose data source
      week 7 may delete. Gate it on the status-change subset with a minimum-n gate. Power: 200-400 status-change games gives a paired-Brier SE near 0.0015-0.002
      and an MDE near 0.004-0.005, plausibly above the true effect. **This test may not
      resolve even after a full season.** If the gate is not met, report as
      collection-in-progress, never as evidence of market efficiency.

## Known blocker

**Point-in-time availability data does not exist historically.** `nba_api`'s inactive list
arrives in the box score, a post-game artifact with no announcement timestamp, and there is
no free retrospective archive of NBA injury-report publication times. The same defect hits
the NHL starting goalie, which was the stated reason NHL is the right second sport.

Consequence: the flagship edge hypothesis is **forward-only from the 2026-27 season**, and
the historical backtest uses schedule-derived features only. The shipped explainability
story until then is team strength and schedule, **not individual players**.

Goalie identity enters only once the forward collector captures announcement timestamps. A
historical fit with actual starters is **uninterpretable in sign**, not an upper bound:
leakage can bias either direction and the gap does not decompose into leakage plus signal.

## Out of scope

- Spreads, totals, player props.
- Draft and roster-trajectory modeling as a **scored** component. ~9 correlated futures
  labels per season cannot support a calibration score. It stays a writeup section
  explicitly labeled speculative and non-scored.
- Live betting or any staking system.
- Sports beyond NBA and NHL.

## CI/CD and distribution

- [x] GitHub Actions: tests and lint on push (`.github/workflows/tests.yml`, week 4).
      Runs the suite on Ubuntu, Windows and macOS (added 2026-09-16, when Windows
      support landed); lint runs once, on Linux.
      Installs the `store` extra but NOT `model`, so weeks 1-7 do not pay for a jax
      toolchain; the suite is offline by construction because `conftest.py` replaces
      `socket.socket`, so CI needs no token and cannot go red because a third-party API
      blinked.
- [x] Separate scheduled workflow for the Phase 6 collector: one long job per day chained
      2-3 times, UTC cron with in-code ET conversion. Credentials out of any fork-triggerable
      workflow; scope the store token append-only.
      **Landed week 4 as `.github/workflows/collector.yml`, deliberately NOT enabled.**
      Triggers are `schedule` and `workflow_dispatch` only — never `pull_request`, which
      would expose the heartbeat secret to any fork that opened a PR. A `concurrency` group
      stops the two chained sessions double-polling at their boundary, and the quote store
      leaves as a build artifact rather than a commit.
- [ ] Published writeup with charts on GitHub Pages. A repo alone is not a portfolio piece.

---

<!-- /autoplan Phase 1 — CEO REVIEW -->
# CEO REVIEW (Phase 1)

Mode: **SELECTIVE EXPANSION** (autoplan override default)
Voices: Claude subagent only. Codex binary not installed → `[subagent-only]`.
Landscape research: WebSearch (Aside not installed).

## 0A. Premise Challenge

| # | Premise as written | Verdict |
|---|---|---|
| 1 | Price banned from headline model, required for nested test | **HOLDS.** Nested test is correctly specified as the sharper claim. |
| 2 | Closing price = home token's last value at or before tipoff | **HOLDS**, strengthened: the two tokens are exact complements (sum 1.0000), so no normalization choice exists. |
| 3 | "Coverage exists; liquidity verified only in a recent window" | **FALSIFIED IN PART, CRITICAL.** See below. |
| 4 | Success is calibration, not accuracy or ROI | **HOLDS.** Matches the literature (Wheatcroft 2022 recommends Brier/log-loss over RPS). |
| 5 | Beating a $1.89M market is unlikely | **HOLDS AND UNDERSTATED.** The plan concedes defeat before starting; see the 10x reframe. |
| 6 | Risk tiers are pre-registered edge buckets | **HOLDS.** |
| 7 | Portfolio piece must be legible without being run | **HOLDS**, and the plan under-serves it. |

### Premise 3 is falsified: this is a TWO-season project, not three

The plan scopes "2023-24 through 2025-26." Every probe behind that scope came from
Oct 2025 or later. Direct probe of the earlier seasons:

| Window | Sports slugs found | NBA per-game volume |
|---|---|---|
| Dec 2023 | 11 `nba-`, 16 `nfl-` | **$6, $0, $0, $0** |
| Mar 2024 | **zero** | — |
| Dec 2024 | 104 `nba-`, 28 `nhl-`, 87 `epl-` | $440k – $618k |
| Dec 2025 | 56 `nhl-`, 3 `nba-` | $1.89M |

2023-24 markets exist but are **dead**. A market with $0 volume has no traded price and
therefore no calibrated probability; ingesting it would inject noise labelled as a
benchmark. March 2024 has no sports markets at all.

**Cascading consequences:**
- Census drops from ~3,900/~4,100 games per sport to roughly **2,460 NBA / 2,624 NHL**.
- Team-by-season pooling drops from **J≈90 to J≈60** (NBA) and **J≈64** (NHL). Still
  identifiable, but the design's stated number is wrong.
- **The dev-side rolling-origin protocol breaks.** Sealing 2025-26 as the holdout leaves
  exactly ONE dev season (2024-25). Rolling origin needs several seasons to roll across.
- Per-game liquidity **quadrupled** between the two usable seasons ($~500k → $~1.9M).
  Pooling across them mixes two different market regimes; price sharpness is not constant.
- A new abbreviation hazard: `nba-lal-no-2023-12-07` uses `no` for New Orleans where
  2025 uses `nop`. **The convention is not stable across seasons**, so the
  learn-the-map probe must run per season.

### 0A questions 2 and 3

**Actual outcome, and is this the most direct path?** The outcome is a career asset plus a
possible product. The plan's most direct path to *that* outcome is not the model. It is the
census and the market-calibration curve, which the plan schedules as a week-3 gate chart and
then sits on for months. See the 10x reframe.

**What if we did nothing?** Nothing breaks; this is a discretionary portfolio project. That
matters: there is no forcing function, so a 10-month calendar with a pre-announced null
headline is the real risk to completion, not technical failure.

## 0B. Existing Code Leverage

Zero code exists, so the leverage map is external rather than internal.

| Sub-problem | What already exists | Plan reuses it? |
|---|---|---|
| Polymarket price history | Gamma + CLOB, unauthenticated, minute fidelity | Yes, verified |
| NBA schedule + box scores | `nba_api` | Yes |
| Bulk Polymarket history | Public datasets: `manja316/polymarket-historical-data` (13,964 markets, 10.8M price records), `SII-WANGZJ/Polymarket_data` (107GB, 1.1B records, 268K markets) | **NO — not evaluated** |
| Calibration metrics | `sklearn.calibration`, Murphy decomposition is ~20 lines | Not named |
| Prior art on the exact question | Reichenbach & Walther, "Accuracy, Skill, and Bias on Polymarket" (SSRN 5910522); "Decomposing Crowd Wisdom: Domain-Specific Calibration Dynamics in Prediction Markets" (arXiv 2602.19520); Wilkens 2026, "Can simple models predict football and beat the odds?"; "A Systematic Review of Machine Learning in Sports Betting" (arXiv 2410.21484) | **NO — uncited** |

**Reuse-ladder failure:** the plan writes a 20,000-request collector without checking
whether the data is already published. The public datasets are third-party and unvetted, so
they are almost certainly not a *replacement* for the census (provenance, NBA/NHL per-game
coverage, and fidelity are all unknown). They are a cheap **cross-validation** of it, which
is worth more than it costs.

**A vendor claim worth rebutting:** one commercial data provider states "the Polymarket
public API only returns live market state without historical endpoints." That is false.
This session pulled 356,231 minute-level points from a resolved market via
`prices-history?...&startTs=...&fidelity=1`. Do not pay for this data.

## 0C. Dream State Mapping

```
  CURRENT STATE              THIS PLAN                    12-MONTH IDEAL
  ──────────────             ──────────                   ──────────────
  Empty repo.                Two-season NBA+NHL           A published, cited
  Verified API               census. Interpretable        instrument that answers
  recipe and a               hierarchical model.          "where is a real-money
  known blocker.             Calibration measured         market miscalibrated, and
  No data on disk.     ───▶  against the market.    ───▶  why" across sports and
                             Nested test probably         liquidity strata, with a
                             null. Availability           reusable public dataset
                             result gated on              behind it. Model is one
                             mid-2027.                    probe among several.
```

**Dream state delta:** the plan moves toward the ideal on instrumentation and rigor, and
away from it on sequencing. It buries the component with a guaranteed positive result
(calibration measurement) behind months of work whose expected output it has already
pre-declared as a null.

## 0C-bis. Implementation Alternatives

```
APPROACH A: Census + calibration, shipped as its own artifact
  Summary: Phases 0-2 only. Census, coverage chart, market calibration curve with
           liquidity and time-to-close strata, published dataset release. Stop there,
           publish, then decide about the model.
  Effort:  M (human ~3-4wk / CC ~3-4 sessions)
  Risk:    Low
  Pros:    Cannot produce a null. Ships in weeks. First-mover value is highest here.
           Is literally the "data-mining skill" demonstration.
  Cons:    No ML modeling shipped, which is the skill the user said they wanted to build.
  Reuses:  Verified API recipe, public datasets for cross-validation.

APPROACH B: Full pipeline, two sports, hierarchical model  [CURRENT PLAN]
  Summary: All six phases as written, corrected to a two-season window.
  Effort:  XXL (historical half ~2mo; availability half gated on mid-2027)
  Risk:    Med-High
  Pros:    Complete. Demonstrates ML depth and real inferential discipline.
           Strongest engineering artifact.
  Cons:    Headline is a pre-announced 0.02-0.03 Brier deficit. Ten-month calendar with a
           possibly-unresolvable flagship test. Highest abandonment risk for a solo builder.
  Reuses:  Everything in A.

APPROACH C: Miscalibration hunt across strata and thin markets
  Summary: Same instrument, different target. Point it where miscalibration is plausible:
           low-volume games, early season, thin categories, non-major leagues. Report
           where a real-money market IS systematically wrong and the structural reason.
  Effort:  L (human ~5wk / CC ~5 sessions)
  Risk:    Med
  Pros:    Positive finding is genuinely likely. Literature directly supports it:
           Polymarket shows no GENERAL longshot bias but bias "concentrated in specific
           categories" (arXiv 2602.19520). Novel and defensible.
  Cons:    Less ML modeling than B. Thin markets are unactionable for real staking.
  Reuses:  A's entire pipeline, pre-registration, and calibration machinery unchanged.
```

**RECOMMENDATION: A now, then C, with B's model as the earned extension.** Maps to the
engineering preference for the smallest diff that cleanly expresses the change, and to
"bias toward action." The user selected B; the A/B inversion and the C promotion are both
escalated as **User Challenges** to the Final Gate rather than auto-decided.

## 0E. Temporal Interrogation

```
  HOUR 1 (foundations)   human ~1h / CC ~10min
    Which seasons are usable? ANSWERED NOW: 2024-25 and 2025-26 only.
    Abbreviation map must be learned PER SEASON, not once.
    ET date comes from the schedule field, never derived from gameStartTime.

  HOUR 2-3 (core logic)  human ~3h / CC ~20min
    Ambiguity they WILL hit: with one dev season, what is the dev/holdout split?
    Rolling origin across seasons is impossible. Must decide: within-season split,
    or a rolling pre-game team-strength state that needs no season intercepts.
    Second ambiguity: do you pool across two seasons whose liquidity differs 4x?

  HOUR 4-5 (integration) human ~5h / CC ~30min
    Surprise: the integrity gate fails on a correct pipeline (noise floor).
    Surprise: the favorite-longshot tilt may not exist at all in NBA/NHL, so a gate
    requiring a signed direction fails for the wrong reason.
    Surprise: 2024-25 markets are 4x thinner, so bid-ask noise is 4x larger there.

  HOUR 6+ (polish/tests) human ~8h / CC ~45min
    Will wish they had planned: prior-art positioning. Four relevant papers exist and
    the plan cites none, so the writeup risks re-deriving a published result.
```

## Step 0.5 — Dual Voices

**CODEX SAYS (CEO — strategy challenge):** `[codex-unavailable: binary not found]`.
No Codex voice this phase.

**CLAUDE SUBAGENT (CEO — strategic independence):** 13 findings, 4 critical, 6 high, 3 medium.
Headline: "the research design is unusually sound and the strategic design is inverted."
Its critical findings: (1) every headline result has a pre-declared expected value of
"nothing happened"; (2) the three-season data volume is an unverified premise carrying the
entire design; (3) the interpretability veto lost its justification but kept its authority;
(4) ten-month calendar, most of it waiting, for the weakest component. Its high findings
add: the dataset is the most valuable output and is treated as plumbing; the 10x reframe is
to point the instrument where miscalibration is plausible; competitive risk sits on the
calibration finding, not the model; Approach A was rejected by deference rather than
analysis; planning itself is now the active risk to shipping; and the project depends on one
unauthenticated third-party endpoint for ten months with no snapshot.

### CEO DUAL VOICES — CONSENSUS TABLE

```
═══════════════════════════════════════════════════════════════════════════
  Dimension                              Claude      Codex   Consensus
  ──────────────────────────────────────  ──────────  ─────   ──────────
  1. Premises valid?                      NO (P3      N/A     FLAGGED
                                          falsified)          (1 voice, verified
                                                               by live probe)
  2. Right problem to solve?              NO          N/A     FLAGGED
                                          (reframe)           (→ User Challenge)
  3. Scope calibration correct?           NO          N/A     FLAGGED
                                          (invert A/B)        (→ User Challenge)
  4. Alternatives sufficiently explored?  NO          N/A     FLAGGED
                                          (A, C by            (→ User Challenge)
                                           deference)
  5. Competitive/market risks covered?    NO          N/A     FLAGGED
                                          (prior art          (auto-decided:
                                           uncited)            add positioning)
  6. 6-month trajectory sound?            NO          N/A     FLAGGED
                                          (10-month           (auto-decided:
                                           calendar)           decouple Phase 6)
═══════════════════════════════════════════════════════════════════════════
CONFIRMED = both agree. Missing voice = N/A, never CONFIRMED.
Single critical finding from one voice = flagged regardless. 0/6 CONFIRMED
(no second voice available). 6/6 FLAGGED by the available voice.
Independent corroboration: finding 2 was confirmed by live API probe, and
findings 6/7 are corroborated by published literature, not by a second model.
```

## Sections 1-10

### Section 1: Architecture Review — 3 findings

```
  ┌──────────────── EXTERNAL (uncontrolled, no contract) ────────────────┐
  │  gamma-api.polymarket.com        clob.polymarket.com     nba_api     │
  │  /markets  /events?slug=         /prices-history         schedule    │
  │            (metadata, labels)    (minute series)         box scores  │
  └───────┬──────────────────────────────┬───────────────────────┬───────┘
          │                              │                       │
          ▼                              ▼                       ▼
  ┌───────────────────────────────────────────────────────────────────────┐
  │  ingest/  — cached HTTP, rate limiter, backoff, resumable state       │
  │            slug builder (PER-SEASON abbr map, ET date from schedule)  │
  │            invariant: |p_home + p_away - 1| < 1e-6  → FAIL LOUD       │
  └───────────────────────────────┬───────────────────────────────────────┘
                                  ▼
  ┌───────────────────────────────────────────────────────────────────────┐
  │  SNAPSHOT RELEASE (immutable)  ← SPOF mitigation, week 1              │
  └───────────────────────────────┬───────────────────────────────────────┘
                                  ▼
  ┌───────────────────────────────────────────────────────────────────────┐
  │  DuckDB   games │ prices(token,minute) │ join_map │ features          │
  │           feature reads REQUIRE as_of; no unqualified read path       │
  └──────────┬──────────────────────────────────────┬─────────────────────┘
             ▼                                      ▼
  ┌────────────────────┐                 ┌──────────────────────────┐
  │ scoring/           │                 │ model/  numpyro          │
  │ Brier, log loss,   │◀────────────────│ hierarchical logistic    │
  │ Murphy, ECE, Cox,  │                 │ pooled: team-season      │
  │ Clark-West, tiers  │                 │ intercept + HCA          │
  └─────────┬──────────┘                 │ global: rest, B2B, travel│
            ▼                            └──────────────────────────┘
  ┌────────────────────┐
  │ charts/ + writeup  │  ← the actual deliverable (GitHub Pages)
  └────────────────────┘
```

**Data flow, four paths, for the census fetch (the only non-trivial new flow):**

```
  SCHEDULE ──▶ SLUG BUILD ──▶ /events?slug= ──▶ /prices-history ──▶ DuckDB
     │              │               │                  │               │
  happy: game    slug hits      market found      series returned   row written
     │              │               │                  │               │
  nil:   schedule  abbr not in   HTTP 200 + []     history: []      no row; miss
         field     season map    ← AMBIGUOUS:      ← the silent-     classified
         missing   ← per-season  no-market vs      empty trap
                   hazard        wrong-slug
     │              │               │                  │               │
  empty: 0 games   slug builds    market exists     0 pre-tipoff    game recorded
         that day  but $0 vol     but never         points          with NO price
                   ← 2023-24      traded            ← dead market   ← MUST be
                     regime                                           excluded
     │              │               │                  │               │
  error: nba_api   —              429 / 5xx         429 / timeout   partial write
         down                     ← backoff,        ← same          ← needs txn
                                    resumable                         or idempotency
```

**F1 [HIGH] The empty-history and no-market cases are indistinguishable from a
misbuilt slug, and the plan's only mitigation is a classification instruction.**
Three distinct conditions collapse to the same observable (`[]` or a miss): the market
genuinely does not exist, the market exists but was never traded (the 2023-24 regime), and
the slug used the wrong abbreviation for that season. The plan says "classify every miss"
without saying how. Auto-decided fix (P5, explicit over clever): make the classifier
mechanical, not judgmental. For every miss, re-probe with a fixed candidate-abbreviation
list for that team-season; only after all candidates miss is it recorded
`no_market`. Record the attempted slug set on every miss row.

**F2 [HIGH] Single point of failure: one unauthenticated third-party endpoint, no
contract, for a multi-month project.** Slug conventions, fidelity semantics, the offset
ceiling, rate limits, and Polymarket's US sports product itself are outside the project's
control, and the 2023-vs-2025 abbreviation drift proves the conventions actually do change.
Auto-decided fix (P2, blast radius, <1d CC): snapshot the full historical pull to an
immutable release in week 1 and run every downstream phase against the snapshot, never
against the live API.

**F3 [MEDIUM] Coupling: the scoring module is coupled to a specific closing-price
construction.** The plan requires two constructions (last value, trailing-15-min VWAP), so
`closing_price` must be a parameter of the scoring interface, not a column baked into the
games table. Auto-decided: scoring takes `price_fn` as an argument.

**Scaling:** 10x is fine (DuckDB handles 690M rows on one machine). What breaks first is not
compute, it is the API: 20,000 requests at any sane rate limit is hours, and re-running it
from scratch after a failure is the real cost. Resumable cache is therefore load-bearing, not
a nicety.

**Rollback posture:** trivial. No service, no migrations, no users. Rollback is `git revert`
plus re-pointing at a prior snapshot release. Reversibility 5/5.

### Section 2: Error & Rescue Map — 4 GAPS

```
  METHOD/CODEPATH             | WHAT CAN GO WRONG                | EXCEPTION CLASS
  ----------------------------|----------------------------------|---------------------
  ingest.fetch_market(slug)   | HTTP 429 rate limited            | HTTPError(429)
                              | HTTP 5xx / gateway              | HTTPError(5xx)
                              | connection timeout               | Timeout
                              | HTTP 200 + empty list []         | (none — silent)
                              | clobTokenIds missing on market   | KeyError
                              | clobTokenIds is a STRING array   | JSONDecodeError
  ingest.fetch_history(token) | HTTP 200 + history: []           | (none — silent)
                              | startTs rejected as too long     | HTTPError(400)
                              | series sums != 1 across tokens   | (none — silent)
  ingest.build_slug(game)     | abbr missing for that season     | KeyError
                              | ET date derived, not from sched  | (none — silent)
  label.resolve(market)       | outcomePrices == ["0.5","0.5"]   | (none — silent)
                              | market unresolved / UMA dispute  | (none — silent)
  store.write(rows)           | partial write mid-census         | (none — silent)
  model.fit()                 | divergent transitions            | (none — warning)
                              | R-hat > 1.01                     | (none — warning)
  ----------------------------|----------------------------------|---------------------

  EXCEPTION / CONDITION        | RESCUED? | RESCUE ACTION              | OPERATOR SEES
  -----------------------------|----------|----------------------------|------------------
  HTTPError(429)               | Y        | exp backoff + resume       | progress log
  HTTPError(5xx), Timeout      | Y        | retry 3x then park slug    | parked-slug count
  HTTP 200 + [] (market)       | N ← GAP  | —                          | silent undercount
  HTTP 200 + [] (history)      | N ← GAP  | —                          | game w/ no price
  sum(p_home,p_away) != 1      | Y        | assert, FAIL LOUD          | crash w/ slug
  KeyError (abbr/season)       | N ← GAP  | —                          | silent miss
  outcomePrices 0.5/0.5        | N ← GAP  | —                          | 0.5 label ingested
  divergences / R-hat          | N ← GAP  | —                          | bad posterior used
  -----------------------------|----------|----------------------------|------------------
```

**F4 [CRITICAL] Four silent-failure gaps, and every one of them corrupts the benchmark
rather than crashing.** This is the exact class the plan's own "cannot quietly lie" claim is
supposed to prevent, and the plan does not name a single one of them. Auto-decided fixes
(P1 completeness; Prime Directive 1, zero silent failures):

- **Empty market / empty history** → never a bare skip. Write a `misses` table row with
  the slug, the attempted abbreviation set, the HTTP status, and a reason enum
  (`no_market`, `never_traded`, `slug_unresolved`). The census reconciliation line must
  balance: `scheduled == priced + misses`, asserted.
- **Missing season abbreviation** → raise, do not skip. A `KeyError` on the abbr map is a
  map bug, and skipping it silently undercounts coverage, which is the project's gate metric.
- **`["0.5","0.5"]` labels** → excluded from scoring at the query level and counted on the
  reconciliation line, not filtered ad hoc in a notebook.
- **MCMC diagnostics** → a fit with divergences or R-hat > 1.01 must raise, not warn. A
  quietly non-converged posterior produces a real-looking Brier score, which is worse than
  a crash.

**No catch-all.** `except Exception` anywhere in `ingest/` would swallow exactly these four.
Flagged pre-emptively.

### Section 3: Security & Threat Model — 1 finding

Examined: attack surface, input validation, authorization, secrets, dependency risk, data
classification, injection vectors, audit logging. The surface is genuinely small. There is no
user input, no auth boundary, no endpoint this project exposes, no PII, no payment data, no
LLM in the loop, and every external call is a read-only GET against a public API. Most of
this section is legitimately N/A and that is stated rather than assumed.

**F5 [MEDIUM] Dependency and supply-chain risk is unassessed, and one dependency is an
unofficial scraper.** `nba_api` is a community-maintained unofficial client against an
undocumented endpoint: it breaks when the NBA changes its API and it has no stability
guarantee. `numpyro` pulls JAX, a large native-dependency tree. Auto-decided (P1): pin every
dependency with a lockfile, and vendor the NBA schedule (date, away, home) to CSV in the
snapshot release so an `nba_api` break cannot invalidate an already-collected census.

**Not a security issue but adjacent, worth stating:** the public GitHub datasets identified
in 0B are untrusted third-party artifacts. If they are used for cross-validation, treat them
as data to compare against, never as ground truth, and never execute code from those repos.

### Section 4: Data Flow & Interaction Edge Cases — 2 findings

No UI, so the interaction table reduces to the batch and scheduled paths.

```
  INTERACTION            | EDGE CASE                        | HANDLED? | HOW
  -----------------------|----------------------------------|----------|---------------
  Census run (batch)     | interrupted at 8,000 of 20,000   | Y        | resumable cache
                         | re-run duplicates rows           | N ← GAP  | need idempotency
                         | rate-limited for hours           | Y        | backoff + park
  Forward collector      | two polls land in same minute    | N ← GAP  | need dedup key
    (scheduled)          | GH Actions run dropped entirely  | PARTIAL  | measured, not fixed
                         | tipoff moves after schedule pull | N ← GAP  | stale target
                         | season ends, cron keeps firing   | N ← GAP  | no stop condition
  Model fit              | one dev season only              | N ← GAP  | protocol broken
  Scoring                | game priced but label missing    | N ← GAP  | see F4
```

**F6 [HIGH] The census is not idempotent.** Re-running after a partial failure can
double-insert price rows, and a duplicated minute series silently changes a VWAP and a
closing price. Auto-decided (P1): primary key on `(sport, game_id, token_id, ts)` with
upsert semantics, plus a row-count reconciliation assert per game.

**F7 [MEDIUM] The forward collector has no stop condition and no stale-target handling.**
Tipoffs move; the plan pulls the day's schedule once. Auto-decided (P3, pragmatic):
re-read `gameStartTime` on each poll rather than trusting the morning snapshot, key snapshots
on `(game_id, poll_ts)`, and gate the workflow on an explicit season-active date range.

### Section 5: Code Quality Review — 1 finding

Examined the planned module structure against the stated engineering preferences. The
`ingest/ → snapshot → store → model → scoring → charts` decomposition is sound, the `as_of`
mandatory-parameter design is the right shape for the leakage requirement, and nothing in the
plan is over-abstracted. No DRY violations are possible yet (zero code).

**F8 [MEDIUM] `statsmodels` is still listed as an alternative to `numpyro` in the design
doc's stack line and cannot fit this model.** `BinomialBayesMixedGLM` is variational and
cannot express multiple partially pooled coefficients with a random walk. Auto-decided (P5):
drop the "or statsmodels" and state numpyro outright, with the MCMC diagnostic work budgeted.
PLAN.md already says numpyro; the design doc's "or" is the stale copy.

### Section 6: Test Review — 3 GAPS, the weakest section of the plan

```
  NEW DATA FLOWS:            census fetch; label join; feature build; scoring
  NEW CODEPATHS:             slug build (per-season); miss classification;
                             closing-price extraction x2 constructions; edge bucketing
  NEW ASYNC WORK:            forward collector (scheduled, from Oct 2026)
  NEW INTEGRATIONS:          Gamma, CLOB, nba_api
  NEW ERROR PATHS:           the 8 rows in Section 2
```

| Item | Test type | In plan? | Happy | Failure | Edge |
|---|---|---|---|---|---|
| `as_of` point-in-time | Integration | **YES** | truncated == full DB | — | — |
| Slug build per season | Unit | **NO** | known slug round-trips | unknown abbr raises | `no` vs `nop` both eras |
| ET date convention | Unit | **NO** | evening game → prior ET date | — | **DST boundary (Mar/Nov)** |
| Complementarity invariant | Unit | partial | sum == 1 | sum != 1 raises | — |
| Miss classification | Unit | **NO** | no_market vs never_traded vs unresolved | — | $0-volume market |
| Closing-price extraction | Unit | **NO** | last pre-tipoff value | no pre-tipoff points | flat-run staleness flag |
| Census reconciliation | Integration | **NO** | scheduled == priced + misses | — | — |
| Clark-West statistic | Unit | **NO** | known-input regression | — | degenerate null case |
| Murphy decomposition | Unit | **NO** | components sum to Brier | — | single-bin case |
| MCMC convergence | Integration | **NO** | R-hat < 1.01 | divergences raise | — |

**F9 [CRITICAL] The plan specifies exactly one test (the `as_of` truncation test) for a
system whose entire value rests on numerical correctness.** The closing-price extraction, the
ET date convention, and the Murphy decomposition are each a single silent off-by-one away
from invalidating every chart, and none has a test. Auto-decided (P1 completeness, and the
stated preference "I'd rather have too many tests than too few"): the ten rows above become
the test plan, with three designated P1.

**The 2am-Friday test:** the census reconciliation assert. If `scheduled == priced + misses`
holds and every miss carries a reason, the coverage chart cannot be silently wrong, and the
coverage chart is the project gate.

**The hostile-QA test:** feed the scorer a perfectly calibrated synthetic market and assert
it reports near-zero miscalibration; then feed it a deliberately miscalibrated one and assert
it catches the tilt in the right direction. This tests the instrument before the instrument
judges the market, which no part of the plan currently does.

**The chaos test:** kill the census at a random request index and assert a resumed run
produces byte-identical output to an uninterrupted run. Directly tests F6.

No LLM or prompt code in this plan, so the eval-suite check is N/A.

### Section 7: Performance Review — 1 finding

Examined row counts, memory, indexing, caching, and the request budget. 69M price rows was
the three-season estimate; at two seasons it is roughly **46M rows**, comfortable for DuckDB
on a laptop. Caching is already the design (on-disk HTTP cache). No N+1 concern exists
because there is no ORM.

**F10 [MEDIUM] The plan stores full minute-level series for every game but every stated
analysis needs only a handful of points per game** (close, T-1h, T-6h, T-24h, plus a
15-minute window for the VWAP). 46M rows is being carried to compute roughly 5 values per
game. Auto-decided (P3, pragmatic): keep the raw series in the snapshot release, since that
is the valuable public artifact, but materialize a narrow `game_prices` table for all
modeling and scoring so the analysis never scans 46M rows.

### Section 8: Observability & Debuggability Review — 2 GAPS

**F11 [HIGH] A 20,000-request census has no progress, no structured logging, and no
resumability telemetry specified.** When it stalls at request 14,000, the operator needs to
know which sport, which season, which slug, and why. Auto-decided (P1): structured JSONL run
log with one line per request (slug, status, latency, cache hit, reason-on-miss), plus a
run manifest recording season windows, the abbreviation map version, and totals.

**F12 [HIGH] The forward collector runs unattended for six months with no alerting.** The
plan acknowledges GitHub Actions drops runs and auto-disables after 60 days of inactivity, and
then does nothing about it. Auto-decided (P1): emit a daily heartbeat summary (games expected,
snapshots captured, gaps) and fail the workflow loudly on a zero-capture day so the failure is
visible in the Actions tab rather than discovered in 2027.

**Debuggability, 3 weeks post-run:** with F11's manifest plus the snapshot release, yes, any
chart is reconstructible from artifacts alone. Without them, no.

### Section 9: Deployment & Rollout Review — 1 finding

No migrations, no service, no users, no feature flags needed. Rollout is a dataset release
plus a static site. Post-run verification is the reconciliation assert plus the market
calibration gate.

**F13 [MEDIUM] `.gitignore` excludes `*.duckdb` and `data/` (correct), but the plan's
snapshot release has no stated mechanism.** Auto-decided (P3): publish the snapshot as a
versioned GitHub Release asset (Parquet, not DuckDB, for portability), with a checksum and a
manifest. This doubles as the public dataset deliverable.

### Section 10: Long-Term Trajectory Review

- **Technical debt introduced:** low. The main debt is the deferred integrity-gate
  simulation and the unresolved dev/holdout split, both already recorded.
- **Path dependency:** the snapshot-first architecture makes future changes *easier*, since
  every downstream phase can be re-run against frozen input.
- **Knowledge concentration:** the design doc is unusually thorough; a new reader can
  reconstruct the reasoning. The gotchas block alone saves days.
- **Reversibility: 5/5.** No users, no data migrations, no external commitments.
- **Ecosystem fit:** uv, DuckDB, Parquet, numpyro are all current and well-supported.
- **The 1-year question:** yes, obvious in 12 months, with one exception. The decision to
  exclude 2023-24 must be written into the plan with its evidence, or a future reader will
  "fix" the missing season and silently reintroduce dead markets.

**Platform potential:** the census plus calibration machinery is genuinely reusable across
every sport Polymarket prices. That is the strongest trajectory argument for the
dataset-as-deliverable expansion.

### Section 11: Design & UX Review — SKIPPED (no UI scope detected)

UI scope grep returned one match (`component`, at PLAN.md:172, meaning "a scored component"),
below the 2-match threshold and a confirmed false positive. No screens, forms, or user-facing
interaction flows exist in this plan. The only human-facing surface is a static writeup, whose
chart design is covered by Sections 6 and 8 rather than by UX review.

## Required Outputs (Phase 1)

### Failure Modes Registry

```
  CODEPATH                  | FAILURE MODE              | RESCUED? | TEST? | OPERATOR SEES  | LOGGED?
  --------------------------|---------------------------|----------|-------|----------------|--------
  ingest.fetch_market       | 429 / 5xx / timeout       | Y        | N←GAP | progress log   | Y
  ingest.fetch_market       | HTTP 200 + []             | N←GAP    | N←GAP | SILENT ←CRIT   | N←GAP
  ingest.fetch_history      | history: []               | N←GAP    | N←GAP | SILENT ←CRIT   | N←GAP
  ingest.fetch_history      | tokens sum != 1           | Y        | Y     | crash w/ slug  | Y
  ingest.build_slug         | abbr missing for season   | N←GAP    | N←GAP | SILENT ←CRIT   | N←GAP
  ingest.build_slug         | ET derived, not schedule  | N←GAP    | N←GAP | SILENT ←CRIT   | N←GAP
  label.resolve             | ["0.5","0.5"] postponed   | N←GAP    | N←GAP | SILENT ←CRIT   | N←GAP
  label.resolve             | unresolved / UMA dispute  | N←GAP    | N←GAP | SILENT ←CRIT   | N←GAP
  store.write               | duplicate rows on re-run  | N←GAP    | N←GAP | SILENT ←CRIT   | N←GAP
  model.fit                 | divergences / R-hat>1.01  | N←GAP    | N←GAP | warning only   | partial
  scoring.closing_price     | flat-run staleness        | PARTIAL  | N←GAP | flagged split  | Y
  scoring.integrity_gate    | false-fire on good data   | N←GAP    | N←GAP | project killed | Y
  collector.poll            | GH Actions run dropped    | PARTIAL  | N←GAP | nothing ←CRIT  | N←GAP
  collector.poll            | season over, cron fires   | N←GAP    | N←GAP | wasted runs    | N
  --------------------------|---------------------------|----------|-------|----------------|--------
  TOTAL: 14 modes.  CRITICAL GAPS (unrescued + untested + silent): 8
```

Eight critical gaps. Every one of them corrupts a number rather than crashing, in a project
whose headline claim is that it cannot quietly lie. All eight have auto-decided fixes above
and appear as P1 tasks below.

### "What already exists"

See 0B. Summary: the API recipe is verified and reusable; `nba_api` covers schedules;
two large public Polymarket datasets exist and are **unevaluated**; four relevant papers
exist and are **uncited**; `sklearn.calibration` plus ~20 lines covers the metrics. Nothing
in this repo is being rebuilt, because nothing in this repo exists yet.

### "NOT in scope" (deferred, with rationale)

| Item | Rationale |
|---|---|
| 2023-24 season | Falsified by probe: $0-volume markets are not calibrated prices |
| Spreads, totals, player props | Verified slug format covers game-winner only |
| Draft/roster modeling as a scored component | ~9 correlated futures labels per season cannot support a calibration score |
| Soccer, tennis, cricket | Coverage confirmed dense but out of the two-sport scope; the pipeline generalizes if wanted later |
| Live/in-game markets | Different data shape, different question |
| Any staking or bet-placement system | Not the project, and not a thing this repo should contain |
| Phase 6 RESULTS (availability hypothesis) | Excluded from the December deliverable by arithmetic: ~5 weeks of forward data by end of November vs a 200-400 game minimum-n gate. Collector runs; results are a 2027 follow-up |
| Availability source work beyond one week-4 slot | Timeboxed. If the source cannot be proven in that slot, collect prices only. Protects model weeks |
| Neural representation transfer | Vetoed by the interpretability constraint |
| Paid data vendors | Unnecessary; the free API returns full minute history (vendor claim to the contrary is false) |

### SELECTIVE EXPANSION — cherry-pick decisions (auto-decided)

| # | Expansion | Effort (human / CC) | Decision | Principle |
|---|---|---|---|---|
| E1 | Publish the census as a documented public dataset release | ~4h / ~20min | **ACCEPTED** | P1, P2 |
| E2 | Stratify the calibration curve by liquidity and time-to-close | ~3h / ~15min | **ACCEPTED** | P1, P2 |
| E3 | Fit a GBM as a reported benchmark *ceiling*, not a shipped model | ~1d / ~30min | **ACCEPTED** | P1 |
| E4 | Immutable snapshot at end of census (week 3); all phases run against it | ~3h / ~15min | **ACCEPTED** | P2 |
| E5 | Cross-validate the census against the public GitHub datasets | ~3h / ~15min | **ACCEPTED** | P4 |
| E6 | Prior-art positioning section in the writeup | ~4h / ~20min | **ACCEPTED** | P1 |
| E7 | Decouple Phase 6 from project completion | ~0 / ~0 | **ACCEPTED** | P6 |
| E8 | Hostile-QA synthetic-market test of the scorer | ~2h / ~10min | **ACCEPTED** | P1 |
| E9 | Split the integrity gate: hard invariants vs descriptive reporting | ~4h / ~20min | **ACCEPTED** | P5 |
| E10 | Promote the miscalibration hunt (Approach C) to co-headline | ~1wk / ~1 session | **USER CHALLENGE** | — |
| E11 | Invert A/B: ship census+calibration first, model as extension | ~0 / ~0 | **USER CHALLENGE** | — |
| E12 | Rolling pre-game team-strength state instead of team-season intercepts | ~1d / ~40min | **TASTE** | P5 |

Accepted: 9. User Challenges: 2. Taste: 1 (plus E1 and E3 flagged as taste at the gate
because they touch user-stated scope and the user-stated interpretability constraint).

### Diagrams produced

1. System architecture with external-boundary and SPOF annotation (Section 1)
2. Census data flow with all four shadow paths (Section 1)
3. Dream-state delta (0C)
4. Error/rescue tables (Section 2)
5. Failure modes registry (above)

State machine and deployment-sequence diagrams: N/A. No stateful objects and no
multi-step deploy exist in this plan.

### Stale Diagram Audit

No pre-existing ASCII diagrams in the repo (one commit, two docs, zero code). Nothing stale.
The design doc's architecture description now conflicts with this review on two points
(three-season window, `statsmodels` as an option) and is amended below.

## Implementation Tasks (CEO phase)

- [ ] **T1 (P1, human: ~2h / CC: ~15min)** — plan/docs — Correct the usable-season window to 2024-25 and 2025-26 everywhere
  - Surfaced by: 0A Premise Challenge — Dec 2023 NBA volumes are $6/$0/$0/$0; Mar 2024 has zero sports slugs
  - Files: PLAN.md, docs/designs/chira-market-calibration-engine.md
  - Verify: no remaining reference to "2023-24"; census request budget and J values updated
- [ ] **T2 (P1, human: ~4h / CC: ~25min)** — ingest — Close the 8 silent-failure gaps with a `misses` table and a balancing reconciliation assert
  - Surfaced by: Section 2 Error & Rescue Map — 4 GAPS; Failure Modes Registry — 8 CRITICAL GAPS
  - Files: ingest/fetch.py, ingest/slug.py, store/schema.sql
  - Verify: `scheduled == priced + misses` asserts; every miss row carries a reason enum and attempted slug set
- [ ] **T3 (P1, human: ~3h / CC: ~20min)** — ingest — Learn the abbreviation map PER SEASON, not once
  - Surfaced by: 0A — `nba-lal-no-2023-12-07` vs `nba-nop-lal-2025-11-30`; conventions drift across seasons
  - Files: ingest/abbr.py
  - Verify: unit test asserts `no` and `nop` both resolve in their own era; unknown abbr raises
- [ ] **T4 (P1, human: ~20-30h / CC: ~2h)** — tests — Build the 23-row test plan (superseded the 10-row estimate; several rows need fixtures or fault injection). **Only the 7 designated P1 tests are required for December**; the other 16 are explicitly "written if time"
  - Surfaced by: Section 6 Test Review — plan specifies exactly one test for a numerically-critical system
  - Files: tests/
  - Verify: ET/DST boundary test, closing-price extraction test, Murphy-sums-to-Brier test all green
- [ ] **T5 (P1, human: ~2h / CC: ~10min)** — model — Raise on MCMC divergences or R-hat > 1.01
  - Surfaced by: Section 2 — a quietly non-converged posterior yields a real-looking Brier score
  - Files: model/fit.py
  - Verify: deliberately under-sampled fit raises rather than warns
- [ ] **T6 (P1, human: ~3h / CC: ~15min)** — ingest/store — Make the census idempotent
  - Surfaced by: Section 4 F6 — re-run after partial failure double-inserts price rows
  - Files: store/schema.sql, ingest/run.py
  - Verify: chaos test — kill at a random request index, resumed run is byte-identical
- [x] **T7 (P2, human: ~3h / CC: ~15min)** — ingest — Snapshot to an immutable Parquet release at the end of the census (week 3, not week 1 — you cannot snapshot data you have not collected); all phases read the snapshot
  - Surfaced by: Section 1 F2 — one unauthenticated third-party endpoint, no contract, multi-month project
  - Files: ingest/snapshot.py, .github/workflows/release.yml
  - Verify: every downstream phase runs with the network disabled
- [ ] **T8 (P2, human: ~4h / CC: ~20min)** — scoring — Split the integrity gate into hard invariants and descriptive reporting
  - Surfaced by: Section 8 / Reviewer Concerns — thresholds sit at or below the estimator noise floor and will false-fire
  - Files: scoring/integrity.py, PREREGISTRATION.md
  - Verify: simulated perfectly-calibrated market passes the hard gate; ECE/slope/tilt report against simulated noise bands
- [x] **T9 (P1, human: ~12-20h / CC: ~1-2h)** — scoring/charts — Headline-2 stratified calibration: within-season volume deciles, season phase, and time-to-close
  - Surfaced by: 0C-bis Approach C + literature (arXiv 2602.19520: bias concentrated in specific categories)
  - Files: scoring/calibration.py, charts/calibration.py
  - Verify: pre-registered 2x2 (2 liquidity x 2 season-phase); minimum ~150 games per
    probability bin with bins merged upward when short; **calibration-slope difference
    between strata as the single primary directional test**, not a grid of curves;
    bootstrap resamples GAMES not rows (time-to-close is a repeated measure, four looks at
    one sample); volume definition frozen in the snapshot with a content hash
  - Note: earlier estimate of ~4h was 3-5x low, and the promotion from P2 to P1 is applied here
  - **DONE 2026-09-21** (`src/chira/strata.py`, `scripts/run_headline2.py`,
    `docs/charts/chart3-headline2.png`, `docs/charts/headline2.json`,
    notes/week5-headline2.md). Primary test: the NBA Cox slope is **+1.398 in low-liquidity
    games against +0.586 in high-liquidity games, a difference of +0.812 with 95% CI
    [+0.618, +1.033]**, one-sided p = 0.0000 on n=1,148/1,146, zero failed replicates. Both
    seasons independently exclude zero, as do all four time-to-close looks and both
    staleness subsets, and low exceeds high in **all 8** sport-season x phase pairs
    including NHL. The obvious artifact was tested and rejected: caliper-matching on
    |logit p| equalises the price spread (sd 0.595 vs 0.593) and returns +0.804
    [+0.559, +1.057]. Per-cell claims are deliberately not made -- at NHL n=225 the null
    ECE p99 is 0.1288, so single cells are close to unfalsifiable.
- [ ] **T10 (P2, human: ~2h / CC: ~10min)** — scoring — Hostile-QA synthetic-market test of the scorer
  - Surfaced by: Section 6 — the instrument is never validated before it judges the market
  - Files: tests/test_scorer_synthetic.py
  - Verify: perfectly-calibrated synthetic → near-zero miscalibration; deliberately tilted → caught, correct sign
- [x] **T11 (P2, human: ~4h / CC: ~20min)** — docs — ~~Publish the census as a documented dataset release~~ **RESCOPED 2026-09-22 (E18): no dataset release.** Ship the collector code and a reproduction path instead; the census is regenerated from the public API by whoever wants it. The terms define Data to include aggregated forms, so an aggregate-only release was not the safe middle it appeared to be
  - Surfaced by: Subagent CEO finding 5 — highest-value output treated as plumbing
  - Files: docs/dataset.md, .github/workflows/release.yml
  - Verify: release asset with checksum, manifest, schema, and license
- [ ] **T12 (P2, human: ~4h / CC: ~20min)** — docs — Prior-art positioning section
  - Surfaced by: 0B + Subagent CEO finding 7 — four relevant papers exist, none cited
  - Files: docs/prior-art.md
  - Verify: each of the 4 sources named with a one-line statement of what this project adds
- [ ] **T13 (P2, human: ~3h / CC: ~15min)** — ingest — Structured JSONL run log and run manifest
  - Surfaced by: Section 8 F11 — a 20,000-request census has no progress or failure telemetry
  - Files: ingest/telemetry.py
  - Verify: one line per request; manifest records season windows and abbr-map version
- [ ] **T14 (P2, human: ~2h / CC: ~10min)** — collector — Heartbeat and loud zero-capture failure for the forward collector
  - Surfaced by: Section 8 F12 — runs unattended for six months with no alerting
  - Files: .github/workflows/collector.yml, collector/heartbeat.py
  - Verify: zero-capture day fails the workflow visibly
- [ ] **T15 (P2, human: ~2h / CC: ~10min)** — store — Materialize a narrow `game_prices` table
  - Surfaced by: Section 7 F10 — 46M rows carried to compute ~5 values per game
  - Files: store/schema.sql
  - Verify: modeling and scoring never scan the raw minute table
- [ ] **T16 (P3, human: ~3h / CC: ~15min)** — ingest — Cross-validate the census against public GitHub datasets
  - Surfaced by: 0B reuse-ladder failure — two large public datasets exist, unevaluated
  - Files: scripts/crossval_public.py
  - Verify: per-game price agreement reported; disagreements enumerated, not averaged away
- [ ] **T17 (P3, human: ~1d / CC: ~30min)** — model — Fit a GBM as a reported benchmark ceiling
  - Surfaced by: Subagent CEO finding 3 — interpretability veto is an assertion, not a measurement
  - Files: model/ceiling.py
  - Verify: writeup states the Brier cost of interpretability as a number, GBM not shipped
- [ ] **T18 (P3, human: ~2h / CC: ~10min)** — collector — Season-active date gate and per-poll `gameStartTime` re-read
  - Surfaced by: Section 4 F7 — no stop condition, stale tipoff targets
  - Files: collector/schedule.py
  - Verify: cron no-ops outside the season window

### CEO Review — Completion Summary

```
  +====================================================================+
  |            MEGA PLAN REVIEW — COMPLETION SUMMARY                   |
  +====================================================================+
  | Mode selected        | SELECTIVE EXPANSION (autoplan default)       |
  | System Audit         | 1 commit, 0 code files, 2 docs. Greenfield.  |
  |                      | No CLAUDE.md. TODOS.md created this phase.   |
  | Step 0               | Premise 3 FALSIFIED by live probe:           |
  |                      | two usable seasons, not three.              |
  | Section 1  (Arch)    | 3 issues (2 High, 1 Med)                    |
  | Section 2  (Errors)  | 14 conditions mapped, 4 GAPS                |
  | Section 3  (Security)| 1 issue found, 0 High severity              |
  | Section 4  (Data/UX) | 14 edge cases mapped, 6 unhandled           |
  | Section 5  (Quality) | 1 issue found                               |
  | Section 6  (Tests)   | Diagram produced, 8 of 10 rows untested     |
  | Section 7  (Perf)    | 1 issue found                               |
  | Section 8  (Observ)  | 2 gaps found (both High)                    |
  | Section 9  (Deploy)  | 1 risk flagged                              |
  | Section 10 (Future)  | Reversibility: 5/5, debt items: 2           |
  | Section 11 (Design)  | SKIPPED (no UI scope — 1 false-positive     |
  |                      | match, below 2-match threshold)             |
  +--------------------------------------------------------------------+
  | NOT in scope         | written (8 items)                           |
  | What already exists  | written (2 public datasets + 4 papers       |
  |                      | identified, both previously unevaluated)    |
  | Dream state delta    | written                                     |
  | Error/rescue registry| 14 conditions, 4 unrescued GAPS             |
  | Failure modes        | 14 total, 8 CRITICAL GAPS                   |
  | TODOS.md updates     | 4 items written                             |
  | Scope proposals      | 12 proposed, 9 accepted, 2 user challenges,  |
  |                      | 1 taste                                     |
  | CEO plan             | written (ceo-plans/)                        |
  | Outside voice        | ran (claude subagent) — [subagent-only],    |
  |                      | codex binary not installed                  |
  | Lake Score           | 13/13 recommendations chose complete option |
  | Diagrams produced    | 5 (architecture, data-flow 4-path,          |
  |                      | dream-state, error/rescue, failure modes)   |
  | Stale diagrams found | 0 in repo; 2 design-doc facts corrected     |
  | Unresolved decisions | 3 (listed below)                            |
  +====================================================================+
```

### Unresolved Decisions (escalated to Final Approval Gate)

1. **USER CHALLENGE — invert A/B ordering.** Ship census + calibration as its own artifact
   first; model becomes the earned extension.
2. **USER CHALLENGE — promote the miscalibration hunt (Approach C) to co-headline.**
3. **TASTE — dev/holdout split with only one dev season.** Rolling pre-game team-strength
   state (recommended) vs within-season splits vs team-season intercepts plus random walk.

**Phase 1 complete.** Codex: unavailable. Claude subagent: 13 findings (4 critical, 6 high,
3 medium). Consensus: 0/6 confirmed (no second voice), 6/6 flagged by the available voice,
with finding 2 independently confirmed by live API probe and findings 6-7 corroborated by
published literature. Phase 2 skipped (no UI scope). Phase 2.5 skipped (no DX scope).
Passing to Phase 3 (Eng).

---

<!-- /autoplan Phase 3 — ENG REVIEW (runs last, reviews the amended plan) -->
# ENG REVIEW (Phase 3)

Voices: Claude subagent only. Codex binary not installed → `[subagent-only]`.

## Step 0: Scope Challenge

**1. What existing code solves each sub-problem?** Zero code in repo. External leverage is
mapped in the CEO phase 0B. One new **[Layer 1]** finding this phase, below.

**2. Minimum set of changes:** Phases 0-2 (census + two charts) is the minimum that produces
a publishable result. Phases 3-5 are the model. Phase 6 is severable. This is the substance
of the two User Challenges already escalated.

**3. Complexity check: TRIGGERED.** The plan introduces 7 modules (`ingest`, `store`,
`model`, `scoring`, `charts`, `collector`, `tests`) and far more than 8 files.
**Auto-decided: proceed as-is, no reduction** (autoplan override, P2 boil lakes). The module
count is essential complexity for a data pipeline, not accidental. Logged, not reduced.

**4. Search check — [Layer 1] finding:**

> **DuckDB has a native `ASOF JOIN`**, purpose-built for "give me the value of this property
> as of this time." The plan proposes to hand-roll point-in-time assembly behind a mandatory
> `as_of` parameter and never mentions it. The documented feature-store pattern also carries
> an `availability_delay` concept, which is exactly the primitive Phase 6 needs to encode an
> announcement timestamp versus an event timestamp.

Auto-decided (P4 DRY, reuse ladder rung 3 "native platform feature"): keep the mandatory
`as_of` **API discipline** (it is what prevents an unqualified read path), but implement
feature assembly with `ASOF JOIN` rather than hand-rolled filtering, and model announcement
lag as `availability_delay`. The discipline and the built-in are complementary, not
competing.

**5. TODOS cross-reference:** `TODOS.md` written this session, 4 items. None block this plan.
Two (soccer extension, multinomial scoring) depend on plan tasks T3 and T7.

**6. Completeness check:** the plan is doing the complete version. No shortcut recommended.

**7. Distribution check:** the plan introduces a new artifact (a public Parquet dataset
release) and T11 covers the pipeline. **Gap found:** neither document states whether
redistributing Polymarket price history is permitted by their terms of service. Flagged as
a P2 task, not deferred silently.

## Step 0.5 — Dual Voices

**CODEX SAYS (eng — architecture challenge):** `[codex-unavailable: binary not found]`.

**CLAUDE SUBAGENT (eng — independent review):** 17 findings, 9 P1, 6 P2, 2 P3, each with a
confidence score and a quoted motivating line. Two of its numeric claims were independently
verified by probe this session and both were correct against the plan (see R6, R12 below).

### ENG DUAL VOICES — CONSENSUS TABLE

```
═══════════════════════════════════════════════════════════════════════════
  Dimension                              Claude      Codex   Consensus
  ──────────────────────────────────────  ──────────  ─────   ──────────
  1. Architecture sound?                  NO          N/A     FLAGGED
                                          (R1 ordering,       (1 voice; R7
                                           R7 random walk)     converges with
                                                               CEO finding 12)
  2. Test coverage sufficient?            NO          N/A     FLAGGED
                                          (7 more tests,      (adds to CEO
                                           R2 label check)     Section 6 gaps)
  3. Performance risks addressed?         NO          N/A     FLAGGED
                                          (R12 2x row         (verified by
                                           undercount)         probe)
  4. Security threats covered?            PARTIAL     N/A     FLAGGED
                                          (R9 non-JSON 200,
                                           R13 fork secrets,
                                           ToS unchecked)
  5. Error paths handled?                 NO          N/A     FLAGGED
                                          (R9 cache poison,
                                           R5 dead-man)
  6. Deployment risk manageable?          NO          N/A     FLAGGED
                                          (R13 Actions
                                           economics)
═══════════════════════════════════════════════════════════════════════════
0/6 CONFIRMED (no second voice). 6/6 FLAGGED by the available voice.
Two findings independently verified by live probe rather than by a second model.
```

## Section 1: Architecture Review — 6 findings

**[P1] (confidence 9/10) PLAN.md:34-38 vs :107-108 — the pre-registration is scheduled
before the two decisions that determine its contents.** Phase 0 commits
`PREREGISTRATION.md` including "dev-side rolling-origin protocol" and "the numeric integrity
gate", while Phase 4 states the rolling-origin protocol "across seasons is impossible" and
the Reviewer Concerns state the thresholds "would fail a working pipeline." A
pre-registration amended after the fact is worth nothing, and "the git hash is the timestamp"
makes the amendment permanently visible.
**Auto-decided (P1 completeness):** move the Phase 4 blocking decision and the noise-floor
simulation into Phase 0 as strict predecessors. `PREREGISTRATION.md` becomes the LAST
artifact of Phase 0, not the first.

**[P1] (confidence 9/10) PLAN.md:67 — the ground-truth label comes from the same third
party being benchmarked, and a free independent label is never cross-checked.** The chain is
slug abbr → `outcomes` nickname array → index-aligned `clobTokenIds` → `p_home`, under a
home-side-only convention, so an orientation flip mirrors the calibration curve about 0.5
instead of crashing. `nba_api` box scores give the winner independently, for free, for every
game.
**Auto-decided (P1; this is the strongest self-test available in the project and costs one
join):** assert per game that the resolved `outcomePrices` winner equals the box-score
winner, AND that the nickname at the `p_home` index maps to the slug's home abbreviation.
Require 100% agreement; enumerate mismatches, never tolerate them.

**[P1] (confidence 8/10) PLAN.md:85-87 — the integrity gate conflates pipeline validation
with the project's own scientific finding.** The plan says "if a real-money market does not
come out near-calibrated, the label join or the closing-price extraction is broken." That
inference is invalid, and the plan contains its own refutation: bias is "concentrated in
specific categories." A miscalibrated result is ambiguous between a broken pipeline and the
headline result of Approach C, and failure kills the project.
**Auto-decided (P5 explicit over clever) — this REVISES the earlier E9/T8 decision, which
kept the wrong framing:** market calibration gets **no gate authority at all**. Pipeline
validity is established only by tests that do not assume the market is calibrated (label
cross-check, complementarity, reconciliation, shuffled-join, synthetic scorer). Market
calibration becomes a reported result.

**[P1] (confidence 9/10) PLAN.md:152 vs :159 — Phase 6 is titled "the only path to the
availability hypothesis" and specifies only price capture.** No endpoint, publication
cadence, or format is named anywhere for NBA injury reports or NHL starting goalies. Six
months of collection yielding prices and no availability timestamps voids the entire forward
experiment.
**Auto-decided (P1):** name the source and prove it before late October 2026. Run one day of
end-to-end capture and diff two consecutive pulls to confirm a status *change* is observable
with a timestamp.

**[P1] (confidence 9/10) PLAN.md:163-164 vs :698-699 — the zero-capture alert cannot fire
for the collector's most likely failure.** The plan names the cause it cannot catch:
Actions "auto-disabled after 60 days of repo inactivity." A workflow that does not run emits
nothing, so an in-workflow heartbeat is structurally unable to report its own absence.
**Auto-decided (P1):** dead-man's switch. The collector pings an external monitor on
success; the monitor alerts on *absence* of a ping. Plus a keepalive to defeat the 60-day
disable, and a pre-season dry run.

**[P2] (confidence 8/10) PLAN.md:65-67 and :133 — the dev/holdout split confounds market
regime with model quality.** The model is developed on the thin 2024-25 season (~$500k/game)
and scored on the sharp 2025-26 one (~$1.9M/game). The pass band was derived from a market
Brier observed in the sharp window, so it is applied where the benchmark is hardest and
estimated where it is easiest. The single integrity window `[0.165, 0.195]` likewise spans
two regimes.
**Auto-decided (P1):** report market Brier on dev and holdout side by side, state the gap as
a difference against the regime, and pre-register per-regime bands rather than one.

## Section 2: Code Quality Review — 3 findings

**[P1] (confidence 8/10) PLAN.md:121-124 — the "mandatory" random walk is arithmetically
identical to the thing it was introduced to avoid.** With two seasons, the holdout-season
intercept is the dev-season intercept plus a zero-mean increment; its posterior mean IS the
shrunk dev-season estimate, and only the variance changes. The design doc explicitly rejects
that substitution as "the exact roster-turnover problem team-season indexing was introduced
to fix."
**Auto-decided — this RESOLVES the escalated taste item, it is not a taste call:** adopt
option **(a)**, a rolling pre-game team-strength state (Elo-like / state-space) updated game
by game. It is the only option that produces a holdout-season team effect from information
available before each holdout game, it removes the identifiability hole, and it better models
a domain where strength moves within a season. **Cross-phase convergence:** the CEO subagent
independently recommended (a) as finding 12.

**[P1] (confidence 8/10) PLAN.md:96-99 — the point-in-time mechanism validates the read
path and nothing else.** The truncation test is passed by any `WHERE ts <= as_of`, including
one over rows whose timestamps are wrong. Three leaks sit outside it: (i) timestamp
provenance, since `nba_api` publishes no game *end* time and a completion time inferred as
tipoff-plus-constant mis-orders late-finishing games; (ii) model-fit leakage, since
season-level intercepts fitted on a full season and scored inside it use future games to
predict past ones, and feature-store `as_of` does not touch model parameters; (iii)
retroactive mutation, since Gamma metadata is mutable when UMA disputes resolve.
**Auto-decided (P1):** add a **leakage canary that is allowed to fail** — fit once with a
deliberately leaked feature (final margin) and assert Brier collapses below ~0.05, proving
the harness can detect leakage at all. Add a `source_observed_at` column distinct from event
time. Freeze labels in the snapshot with a content hash. Note option (a) above also removes
leak (ii) by construction.

**[P1] (confidence 8/10) PLAN.md:31-32 and :835 — the response cache can poison the census
and the reconciliation assert still balances.** Two compounding problems. First, caching
misses: an early run with an incomplete per-season abbreviation map produces thousands of
empty responses, and if the cache keys on URL, fixing the map does not invalidate them.
Second, non-JSON 200s: these endpoints sit behind a WAF, and a challenge page returns HTTP
200 with an HTML body; classified by shape rather than content-type that becomes
`no_market`, and `scheduled == priced + misses` balances perfectly with a fabricated miss.
The plan's one safety net is blind to its most likely systematic corruption.
**Auto-decided (P1):** cache only responses passing a content-type AND schema check; key the
cache on abbreviation-map version; treat any non-JSON or shape-unexpected response as a
transient error and never as a miss; re-probe every `no_market` row in a second pass and
assert the two passes agree.

## Section 3: Test Review — coverage diagram

```
CODE PATHS                                          DATA / ANALYSIS FLOWS
[+] ingest/                                         [+] Census correctness
  ├── build_slug()                                    ├── [GAP] Label agreement vs nba_api
  │   ├── [GAP] per-season abbr (no/nop)              │         ← STRONGEST self-test
  │   ├── [GAP] ET date from schedule field           ├── [GAP] Shuffled-join collapse
  │   ├── [GAP] DST boundary (Mar/Nov)                │         ← validates the gate itself
  │   └── [GAP] neutral-site / play-in / Cup          ├── [GAP] Reconciliation fault injection
  ├── fetch_market()                                  │         ← assert the assert fires
  │   ├── [GAP] HTTP 200 + []                         └── [GAP] Non-JSON 200 (WAF page)
  │   ├── [GAP] non-JSON 200 body
  │   └── [GAP] 429 / 403 / 503 backoff             [+] Modeling integrity
  ├── fetch_history()                                 ├── [GAP] Leakage canary (must fail)
  │   ├── [★★ ] complementarity assert (partial)      ├── [GAP] MCMC divergence raises
  │   └── [GAP] empty history                         └── [GAP] as_of truncation  ← only
  └── cache                                                     test in the original plan
      └── [GAP] invalidation on abbr-map bump
[+] scoring/                                        [+] Chart integrity
  ├── closing_price()                                 ├── [GAP] Murphy sums to Brier
  │   ├── [GAP] last pre-tipoff value                 └── [GAP] Synthetic calibrated market
  │   ├── [GAP] flat-run staleness flag                         → near-zero miscalibration
  │   └── [GAP] second construction (see R6)
  ├── [GAP] clark_west() known-input regression     [+] Golden fixtures
  └── [GAP] edge bucketing boundaries                 └── [GAP] 3 probed games as JSON
                                                              w/ hand-computed closes

COVERAGE: 1/24 paths tested (4%)  |  the single planned test is as_of truncation
QUALITY: ★★:1 (partial)  |  GAPS: 23
```

**[P1] (confidence 9/10) — the plan specifies 1 test for 24 identifiable paths.** The CEO
phase raised this to 10 rows; the eng voice adds 7 more, and this diagram totals 24.
**Auto-decided (P1, and the stated preference "I'd rather have too many tests than too
few"):** all 23 gaps become the test plan. Designated P1: label agreement, shuffled-join,
leakage canary, non-JSON 200, cache invalidation, ET/DST boundary, closing-price extraction.

**[P2] (confidence 8/10) PLAN.md:145-146 — "trailing-15-minute VWAP" is not computable, and
the average it replaces is approximately the last value anyway. VERIFIED BY PROBE:**
`prices-history` points carry only `{t, p}` — no volume field, so there are no weights.
Volume exists only as a market-level aggregate. And under the documented carry-forward
behaviour (the final 8 pre-tipoff values were identical), a trailing average equals the last
value on most games, so the second construction cannot detect the measurement error it exists
to detect.
**Auto-decided (P3 pragmatic):** replace with two constructions that actually differ — the
last pre-tipoff value, and the **T-1h value** (or the last value that differs from the
terminal flat run). Drop "VWAP" from the vocabulary. Also confirm the `fidelity` unit before
fixing any window at 15 points; it is currently inferred from observed gaps, not documented.

**[P2] (confidence 7/10) PLAN.md:140-142 — Clark-West against a fitted null needs its own
specification.** CW's adjustment term is defined relative to the null's fitted values, so the
two nulls give two different statistics, and B must literally nest the recalibration (B =
`a + b·logit(p) + f(x)` with free `a, b`) or CW does not apply to the second comparison.
PLAN.md also never carries forward the design doc's family-wise policy.
**Auto-decided (P1):** write B's linear predictor explicitly, and carry the primary-test
designation into PLAN.md with everything else labeled exploratory.

**[P3] (confidence 8/10) PLAN.md:98-99 and :851 — "byte-identical" will flake and the two
uses contradict each other.** DuckDB parallel aggregation does not guarantee float summation
order, and T13 requires per-request telemetry with latency and timestamps, which makes a
resumed run byte-different by design.
**Auto-decided (P5):** define equality on a canonically sorted frame with an explicit
tolerance, and exclude run metadata from the comparison.

**[P3] (confidence 8/10) — neutral-site, play-in, and NBA Cup slug cases were dropped
between the design doc and PLAN.md.** These are exactly the games where the away-home slug
convention and the home-side calibration convention both break, and being a handful per
season they will be silently diagnosed as slug misses.
**Auto-decided (P1):** enumerate them from the schedule up front and route them to an
explicit reason enum.

## Section 4: Performance Review — 3 findings

**[P2] (confidence 8/10) PLAN.md:94-95 and :675-676 — the price row count is understated
2x in both places it appears. VERIFIED BY PROBE:** the plan says ~46M rows at two seasons,
but that counts one token. At one row per **token** per minute over 5,084 games at ~9,300
points, the real figure is **94.6M rows**.
**Auto-decided (P1):** correct both figures, partition the Parquet release by sport and
season, and estimate compressed size before committing to a release mechanism.
**Knock-on:** GitHub caps a single release asset at 2GB, and T11 publishes this. Partitioning
is now load-bearing, not cosmetic.

**[P2] (confidence 7/10) PLAN.md:155-157 — Actions economics for the collector are
unexamined and will kill it mid-season.** An 11-hour ET game window polled every 5 minutes is
~130 runs/day for ~180 days. On a private repo that exceeds the free minute allowance many
times over, so the collector dies from quota, not from the delay the plan does model. Actions
also cannot self-schedule per game; a job that sleeps to tipoff burns billed minutes and hits
the 6-hour job cap. And the season window plus daily window are ET concepts on a UTC cron, so
March and November shift by an hour and clip the first or last game of the slate — the same
DST class of bug the plan carefully fixed for slugs.
**Auto-decided (P3 pragmatic):** one long-running job per day chained 2-3 times, or a cheap
always-on host. Pin the cron in UTC with an explicit ET conversion in code. With a public
repo, keep store credentials out of any fork-triggerable workflow and scope the token
append-only.

**[P2] (confidence 8/10) PLAN.md:31-32 — rate limits are the project's schedule risk and no
step measures them.** A conservative fixed delay is the difference between a 4-hour census
and a 3-day one, and it is chosen blind. Backoff is specified for 429 only; WAF blocks arrive
as 403, 503, or the R9 200.
**Auto-decided (P1):** a 10-minute Phase 0 calibration probe that ramps until the first 429
and records reset behaviour; 429 count as first-class telemetry; a circuit breaker so an
unattended run parks instead of backing off for days.

**Not flagged after examination:** N+1 queries (no ORM), connection-pool pressure (single
embedded DuckDB), and caching opportunities (an on-disk HTTP cache is already the design).
DuckDB at 94.6M rows on a laptop is comfortable; the bottleneck is the API, not compute.

## Section 2 addendum: NHL schedule source

**[P2] (confidence 9/10) PLAN.md:30-31 vs :54 — the NHL schedule source is never named.**
Dependencies list `nba_api` only, while Phase 1 requires "the NHL schedule's `gameDate`."
Half the census, and possibly the *primary* sport, rests on an unidentified dependency.
Related: `nba_api` hits stats.nba.com, which commonly blocks cloud egress, so it must not be
called from GitHub Actions.
**Auto-decided (P1):** name the NHL endpoint, probe it, and vendor both schedules to CSV in
the snapshot release so neither dependency can invalidate a collected census.

## Implementation Tasks (Eng phase)

Synthesized from this phase's findings. These were previously written only to the JSONL
artifact and not into the plan, which caused the re-review to see 6 P1 tasks instead of 17.
Corrected here.

- [ ] **E1 (P1, human: ~2h / CC: ~15min)** — tests — Label agreement assert: outcomePrices winner == nba_api box-score winner, and p_home nickname maps to slug home abbr
  - Surfaced by: Eng Section 1 R2 (conf 9/10): ground-truth label comes from the same third party being benchmarked; orientation flip would mirror the curve about 0.5, not crash
  - Files: tests/test_label_agreement.py, ingest/label.py
- [ ] **E2 (P1, human: ~3h / CC: ~20min)** — scoring — Strip all gate authority from market calibration; validate the pipeline only with tests that do not assume calibration
  - Surfaced by: Eng Section 1 R3 (conf 8/10): gate conflates pipeline validation with the project own finding; miscalibration is ambiguous between a bug and the Approach C headline
  - Files: scoring/integrity.py, PREREGISTRATION.md
- [ ] **E3 (P1, human: ~1h / CC: ~10min)** — plan — Reorder Phase 0: the blocking modeling decision and the noise-floor simulation become strict predecessors; PREREGISTRATION.md is the LAST Phase 0 artifact
  - Surfaced by: Eng Section 1 R1 (conf 9/10): pre-registration is committed before the two decisions that determine its contents
  - Files: PLAN.md
- [ ] **E4 (P1, human: ~1d / CC: ~40min)** — model — Adopt a rolling pre-game team-strength state (Elo-like/state-space) instead of team-season intercepts plus random walk
  - Surfaced by: Eng Section 2 R7 (conf 8/10) converging with CEO subagent finding 12: with two seasons the random walk posterior mean IS the shrunk dev-season estimate, so it reintroduces the problem it was meant to fix
  - Files: model/state.py, PLAN.md
- [ ] **E5 (P1, human: ~3h / CC: ~20min)** — tests — Leakage canary that is allowed to fail: fit with final margin leaked, assert Brier collapses below 0.05
  - Surfaced by: Eng Section 2 R8 (conf 8/10): the as_of truncation test validates the read path only; without a canary, no-leakage-detected is unfalsifiable
  - Files: tests/test_leakage_canary.py
- [ ] **E6 (P1, human: ~4h / CC: ~25min)** — ingest — Harden the cache: content-type plus schema check before caching, cache key versioned by abbr-map, non-JSON 200 raises and is never a miss, second-pass re-probe of every no_market
  - Surfaced by: Eng Section 2 R9 (conf 8/10): WAF challenge pages return HTTP 200 with HTML and become fabricated misses that keep the reconciliation assert balanced
  - Files: ingest/cache.py, ingest/fetch.py
- [ ] **E7 (P1, human: ~4h / CC: ~25min)** — collector — Name and prove the availability data source before late Oct 2026; one day of end-to-end capture diffing consecutive pulls to observe a timestamped status change
  - Surfaced by: Eng Section 1 R4 (conf 9/10): Phase 6 is titled the only path to the availability hypothesis and specifies only price capture
  - Files: collector/availability.py, PLAN.md
- [ ] **E8 (P1, human: ~3h / CC: ~20min)** — collector — Dead-man switch: external monitor alerts on ABSENCE of a success ping, plus keepalive against the 60-day Actions auto-disable
  - Surfaced by: Eng Section 1 R5 (conf 9/10): an in-workflow heartbeat cannot report its own absence, which is the most likely failure mode
  - Files: .github/workflows/collector.yml, collector/heartbeat.py
- [ ] **E9 (P1, human: ~3h / CC: ~20min)** — store — Implement point-in-time feature assembly with DuckDB native ASOF JOIN and model announcement lag as availability_delay; keep the mandatory as_of API discipline
  - Surfaced by: Eng Step 0 Search check, [Layer 1]: DuckDB has a native ASOF JOIN purpose-built for as-of lookups; the plan hand-rolls it
  - Files: store/features.py
- [ ] **E10 (P1, human: ~2h / CC: ~15min)** — ingest — Name, probe, and vendor the NHL schedule source; never call nba_api from Actions (stats.nba.com blocks cloud egress)
  - Surfaced by: Eng Section 2 addendum (conf 9/10): NHL schedule source is never named yet half the census depends on it
  - Files: ingest/schedule.py, PLAN.md
- [ ] **E11 (P1, human: ~5h / CC: ~30min)** — tests — Build the remaining 23-gap test plan: shuffled-join collapse, reconciliation fault injection, non-JSON 200, cache invalidation, ET/DST boundary, closing-price extraction, Murphy self-consistency, golden fixtures
  - Surfaced by: Eng Section 3 (conf 9/10): plan specifies 1 test for 24 identifiable paths (4% coverage)
  - Files: tests/
- [ ] **E12 (P2, human: ~2h / CC: ~15min)** — scoring — Replace the impossible trailing-15-min VWAP with two constructions that actually differ (last pre-tipoff value, and T-1h)
  - Surfaced by: Eng Section 3 R6 (conf 8/10), VERIFIED BY PROBE: prices-history points carry only {t,p} with no volume field, so a VWAP has no weights; carry-forward also makes a trailing average equal the last value
  - Files: scoring/closing.py, PREREGISTRATION.md
- [x] **E13 (P2, human: ~2h / CC: ~15min)** — store/docs — Correct the price row count to ~94.6M (two tokens per game, not one) and partition the Parquet release by sport and season
  - Surfaced by: Eng Section 4 (conf 8/10), VERIFIED BY PROBE: plan says 46M in two places; 5084 games x 2 tokens x ~9300 points = 94.6M, and GitHub caps a release asset at 2GB
  - Files: PLAN.md, store/schema.sql, .github/workflows/release.yml
- [ ] **E14 (P2, human: ~2h / CC: ~15min)** — ingest — Phase 0 rate-limit calibration probe: ramp until the first 429, record reset behaviour, add a circuit breaker and 429-count telemetry
  - Surfaced by: Eng Section 4 (conf 8/10): a conservative fixed delay is the difference between a 4-hour and a 3-day census and is currently chosen blind
  - Files: ingest/ratelimit.py
- [ ] **E15 (P2, human: ~3h / CC: ~20min)** — collector — Rework collector scheduling: one long job per day chained, UTC cron with explicit ET conversion in code, credentials out of fork-triggerable workflows
  - Surfaced by: Eng Section 4 (conf 7/10): 130 runs/day x 180 days exceeds the free Actions allowance, and an ET window on a UTC cron clips the slate across DST
  - Files: .github/workflows/collector.yml, collector/schedule.py
- [ ] **E16 (P2, human: ~2h / CC: ~15min)** — scoring — Write B linear predictor explicitly so it literally nests the recalibration null; carry the primary-test designation into PLAN.md
  - Surfaced by: Eng Section 3 R15 (conf 7/10): Clark-West adjustment is defined relative to the null fitted values, so B must nest a + b*logit(p) with free a,b
  - Files: scoring/nested.py, PLAN.md
- [ ] **E17 (P2, human: ~2h / CC: ~15min)** — scoring — Report market Brier on dev and holdout side by side; pre-register per-regime bands instead of one
  - Surfaced by: Eng Section 1 R11 (conf 8/10): model developed on the thin ~500k season and scored on the sharp ~1.9M one, so the pass band is applied where the benchmark is hardest
  - Files: PREREGISTRATION.md, scoring/report.py
- [x] **E18 (P1 — DO IT IN WEEK 1, it is a 20-minute check that can void a week-10 deliverable, human: ~20min / CC: n/a)** — docs — Check Polymarket terms of service on redistributing price history before publishing the dataset
  - **RESOLVED 2026-09-22**, week 5 rather than week 1, because the ToS page renders
    client-side and a fetch returns only the SPA shell: it genuinely needed a human with a
    browser. The promotion to P1 was right — it did void a deliverable (T11's dataset
    release), and it did so before any work was spent building one. See
    notes/week1-tos-check.md
  - Surfaced by: Eng Step 0 Distribution check: neither document states whether redistribution is permitted, and the dataset is proposed as the project most valuable output
  - Files: docs/dataset.md
- [ ] **E19 (P3, human: ~2h / CC: ~15min)** — ingest — Enumerate neutral-site, international, play-in and NBA Cup games up front and route them to an explicit reason enum
  - Surfaced by: Eng Section 3 R17 (conf 8/10): dropped between the design doc and PLAN.md; these are exactly where the away-home and home-side conventions break
  - Files: ingest/special_games.py
- [ ] **E20 (P3, human: ~1h / CC: ~10min)** — tests — Define resume equality on a canonically sorted frame with tolerance, excluding run metadata
  - Surfaced by: Eng Section 3 R16 (conf 8/10): byte-identical will flake since DuckDB parallel aggregation does not fix float summation order and telemetry makes runs differ by design
  - Files: tests/test_resume.py

**December scope split.** Required before December: every P1 above, plus E12 (the nested test
is wrong without it), E13 (the dataset release needs partitioning), E14 (schedule-critical),
E16 (nested-test correctness), E17 (per-regime bands). Deferred past December: E7, E8, E15,
E19, E20 (all collector or polish, and Phase 6 results are out of scope by arithmetic).

### Eng Review — Completion Summary

- **Step 0: Scope Challenge** — scope accepted as-is. Complexity check TRIGGERED (7 modules,
  8+ files); auto-decided proceed, no reduction (autoplan override, P2). One **[Layer 1]**
  reuse finding: DuckDB native `ASOF JOIN`.
- **Architecture Review** — 6 issues found (5 P1, 1 P2)
- **Code Quality Review** — 3 issues found (all P1) + 1 P2 addendum (NHL schedule source)
- **Test Review** — diagram produced, **23 gaps** identified against 24 paths (4% coverage)
- **Performance Review** — 3 issues found (all P2), 2 verified by live probe
- **NOT in scope** — written (CEO phase, 8 items)
- **What already exists** — written (CEO phase 0B, plus the ASOF JOIN finding)
- **TODOS.md updates** — 4 items written
- **Failure modes** — 8 critical gaps flagged (CEO phase registry), all with auto-decided fixes
- **Outside voice** — ran (claude subagent). Codex `[codex-unavailable: binary not found]`
- **Test plan artifact** — written to
  `~/.gstack/projects/Chira/arva-main-eng-review-test-plan-20260911-162634.md`
- **Lake Score** — 20/20 recommendations chose the complete option (eng phase); 59/59 across all phases including the re-review
- **Parallelization** — 3 lanes: (1) ingest + census, (2) scoring + charts, (3) collector.
  Lanes 1 and 3 are parallel; lane 2 is sequential after lane 1.

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| 1 | CEO | Mode = SELECTIVE EXPANSION | Mechanical | override | autoplan default | other 3 modes |
| 2 | CEO | Exclude 2023-24 season | Mechanical | P1 | $0-volume markets have no calibrated price (probed) | 3-season span |
| 3 | CEO | Close 8 silent-failure gaps with a misses table | Mechanical | P1 | Prime Directive 1, zero silent failures | bare skips |
| 4 | CEO | Per-season abbreviation map | Mechanical | P1 | `no` vs `nop` proves drift | one-time map |
| 5 | CEO | Raise on MCMC divergence / R-hat | Mechanical | P1 | non-converged posterior yields a real-looking Brier | warn-only |
| 6 | CEO | Census idempotency via PK + upsert | Mechanical | P1 | re-run double-inserts change a VWAP silently | re-run as-is |
| 7 | CEO | Pin deps + vendor schedule to CSV | Mechanical | P1 | `nba_api` is an unofficial scraper | unpinned |
| 8 | CEO | Immutable snapshot week 1 (E4) | Taste | P2 | SPOF on one third-party endpoint | live-API reads |
| 9 | CEO | Public dataset release (E1) | Taste | P1+P2 | near-zero marginal cost, cannot produce a null | plumbing-only |
| 10 | CEO | Liquidity/time-to-close strata (E2) | Mechanical | P1+P2 | literature: bias is category-concentrated | pooled only |
| 11 | CEO | GBM as reported ceiling (E3) | Taste | P1 | converts an assertion into a measurement | assertion only |
| 12 | CEO | Cross-validate vs public datasets (E5) | Mechanical | P4 | two large public datasets existed unevaluated | build blind |
| 13 | CEO | Prior-art positioning (E6) | Mechanical | P1 | 4 relevant papers uncited | no positioning |
| 14 | CEO | Decouple Phase 6 (E7) | Mechanical | P6 | 10-month calendar on a maybe-unresolvable test | gated completion |
| 15 | CEO | Synthetic-market scorer test (E8) | Mechanical | P1 | instrument never validated before judging | unvalidated |
| 16 | CEO | Narrow `game_prices` table | Mechanical | P3 | 94.6M rows scanned for ~5 values/game | raw scans |
| 17 | CEO | Structured run log + manifest | Mechanical | P1 | 20k requests with no telemetry | silent run |
| 18 | CEO | Collector heartbeat | Mechanical | P1 | 6 months unattended, no alerting | none |
| 19 | ENG | Proceed without scope reduction | Mechanical | P2 | module count is essential complexity | reduce to 3 modules |
| 20 | ENG | Implement PIT with DuckDB `ASOF JOIN` | Mechanical | P4 | native built-in exists; reuse rung 3 | hand-rolled filter |
| 21 | ENG | `PREREGISTRATION.md` becomes LAST Phase 0 artifact | Mechanical | P1 | committed before the decisions that define it | commit first |
| 22 | ENG | Label agreement assert vs `nba_api` | Mechanical | P1 | label came from the benchmarked party itself | trust Gamma |
| 23 | ENG | **REVISES #E9/T8** — market calibration gets NO gate authority | Mechanical | P5 | miscalibration is ambiguous between bug and finding | split-but-still-gating |
| 24 | ENG | Adopt rolling pre-game team-strength state (a) | Mechanical | P5 | random walk over 2 seasons IS the rejected substitution; 2 voices converged | team-season + RW |
| 25 | ENG | Leakage canary that must fail | Mechanical | P1 | "no leakage detected" otherwise unfalsifiable | as_of test only |
| 26 | ENG | Cache hardening (content-type, schema, version key, 2nd pass) | Mechanical | P1 | WAF 200s become fabricated misses that keep the assert balanced | URL-keyed cache |
| 27 | ENG | Name + prove the availability source pre-season | Mechanical | P1 | Phase 6 specifies only price capture | price-only capture |
| 28 | ENG | Dead-man's switch for the collector | Mechanical | P1 | in-workflow heartbeat cannot report its own absence | in-workflow alert |
| 29 | ENG | Replace VWAP with T-1h construction | Mechanical | P3 | no volume field exists (probed); carry-forward makes it a no-op | VWAP |
| 30 | ENG | Correct row count to 94.6M + partition release | Mechanical | P1 | 2x undercount; 2GB release-asset cap | 46M, single asset |
| 31 | ENG | Rate-limit calibration probe + circuit breaker | Mechanical | P1 | blind delay = 4 hours vs 3 days | fixed blind delay |
| 32 | ENG | Rework collector scheduling (1 chained job/day, UTC cron) | Mechanical | P3 | 130 runs/day x 180 days exceeds free tier | 5-min polling |
| 33 | ENG | B must literally nest the recalibration null | Mechanical | P1 | CW adjustment is defined against the null's fitted values | unspecified B |
| 34 | ENG | Per-regime Brier bands | Mechanical | P1 | dev season is 4x thinner than holdout | one band |
| 35 | ENG | Check Polymarket ToS before publishing the dataset | Mechanical | P1 | redistribution permission unstated | publish blind |
| 36 | ENG | Enumerate neutral-site / play-in / Cup games | Mechanical | P1 | dropped between docs; conventions break there | silent misses |
| 37 | ENG | Resume equality on sorted frame with tolerance | Mechanical | P5 | byte-identical flakes by design | byte-identical |

**Totals: 37 auto-decisions logged.** 34 mechanical, 3 taste (#8, #9, #11).
2 User Challenges are NOT in this table because they were never auto-decided.
1 previously-escalated taste item (dev/holdout split) was RESOLVED by decision #24.


## Eng Re-Review of the Amended Plan (22 findings)

Triggered by the Final Gate contract: an accepted User Challenge is amended into the plan,
then Eng re-runs against the final plan. Fresh subagent, focused only on the amendments.
**All 22 findings accepted.** One corrected a material error in the schedule claim.

| # | Sev | Conf | Finding | Disposition |
|---|-----|------|---------|-------------|
| A1 | P1 | 9 | The "~6h CC" figure measures the review remediation backlog, not the project, and drops the paired ~55 human hours. No line exists for the HTTP layer, census runner, store, feature store, model, scoring, charts, or writeup | **Corrected.** Honest effort accounting + capacity assumption + cut order added |
| A2 | P1 | 8 | Week 4 slips first: census validation runs AFTER the week 2-3 snapshot is frozen, so a label-agreement failure forces a re-census | **Fixed.** Validation gate moved to week 2, on the first 200 games |
| A3 | P1 | 8 | Weeks 5-6 carry 23 tests on an estimate written for 10 | **Fixed.** T4 re-estimated; only the 7 designated P1 tests required for December |
| A4 | P1 | 7 | "Elo-like / state-space" are two cost classes; a latent walk is ~75k latent variables on 5,084 observations, with T5 turning divergences into hard failures | **Fixed.** Week-1 pre-commit to deterministic pre-game ratings as a fixed covariate |
| A5 | P2 | 8 | Both named risks are machine time and both are small (census 4-13h, MCMC minutes). The binding constraint is human decision time | **Accepted.** Reflected in the capacity assumption |
| A6 | P2 | 8 | Week 1's prerequisites for week 2 are absent from the schedule; realistic week 1 is 25-35 human hours | **Fixed.** Week 2 now carries the skeleton/HTTP/store work explicitly |
| A7 | P2 | 9 | The ToS check is a week-11 blocker with no earlier slot and can void a deliverable | **Fixed.** E18 promoted to P1, moved to week 1 |
| A8 | P2 | 7 | Holdout opened weeks 7-9 with the writeup immediately after and no second pass | **Fixed.** Full dress rehearsal on dev before the holdout opens |
| B1 | P1 | 8 | The week-4 availability slot cannot execute its own acceptance test: proving a status change needs regular-season injury reports, and the NBA season tips after week 4 ends | **Fixed.** Slot split: week 4 prices-only, week 7 availability proof |
| B2 | P2 | 9 | "One slot" contradicts four standing P1 collector decisions; also needs a third-party monitoring account never named | **Fixed.** Both slots specified; monitoring account chosen in week 4 |
| B3 | P2 | 9 | Phase 6 body still specifies the 5-10 minute polling the review killed | **Fixed.** Decision written back into Phase 6 and the CI/CD section |
| B4 | P2 | 9 | T9's promotion to P1 was never applied to T9's own line, and the strata list omitted early season | **Fixed.** Both |
| B5 | P2 | 9 | Status line and report verdict disagree about whether the challenges are resolved | **Fixed.** Verdict and unresolved block reconciled |
| B6 | P3 | 8 | Snapshot week drifted: T7/E4 say week 1, the schedule says weeks 2-3 | **Fixed.** Corrected to end of census, week 3 |
| B7 | P3 | 7 | Week 1 would pre-register a test whose data source week 7 may delete | **Fixed.** Availability test moved to a separate later-hashed addendum |
| B8 | P3 | 6 | The exclusion arithmetic is NBA-only while NHL is half the census | **Fixed.** Per-sport arithmetic shown (~5 wk NBA, ~8 wk NHL); conclusion holds for both |
| B9 | P3 | 7 | Dropping availability voids the stated reason for the second sport | **Fixed.** NHL rejustified by headline-2 per-stratum n, and flagged as NOT the right cut |
| C1 | P1 | 8 | Liquidity strata are confounded with season regime; the plan documented this confound for the model but not for headline 2 | **Fixed.** Within-season volume deciles; between-season contrast reported separately as confounded |
| C2 | P1 | 8 | Per-stratum ECE at n≈850 has ~2.4x the SE of a noise floor already flagged as failing at full n | **Fixed.** Week-1 noise simulation runs at per-stratum n; min-n pre-registered from it |
| C3 | P1 | 7 | Ten equal-count bins at ~85 games/bin gives SE≈0.054, and the literature's claim is a tail claim, so the informative bins empty out | **Fixed.** 2x2 strata, min ~150 games/bin merged upward, slope-difference as the single primary test |
| C4 | P2 | 8 | Time-to-close is a repeated measure, four looks at one sample; bootstrap must resample games | **Fixed.** Specified in T9's verify line |
| C5 | P2 | 7 | Liquidity is terminal cumulative volume: outcome-correlated and mutable | **Fixed.** Definition frozen with a content hash; caveat reported |
| C6 | P2 | 8 | Headline 2's real cost lands in week 1, and the family-wise policy is missing for ~24 strata cells | **Fixed.** One primary directional test; everything else exploratory |
| C7 | P2 | 9 | "Cannot come back empty" guarantees a measurement, not a finding | **Corrected.** Framing fixed in the headline section; it rebuts how Challenge 2 was originally pitched |
| D | P1 | — | The deliverable is scheduled last with every buffer in front of it, so any slip in weeks 1-9 deletes the artifact rather than delaying it | **Fixed, and it is the most valuable change in the session.** Stage the deliverable: headline 2 ships frozen at end of week 6; headline 1 becomes v2 |

**Cross-phase theme, third occurrence: the noise floor.** The spec-review round, the CEO
phase, and now C2 all land on the same defect from different directions. The week-1
simulation must therefore cover BOTH the full-n gate and the per-stratum n, or headline 2
inherits the exact problem the gate already has.

### Decision Audit Trail — re-review additions (38-60)

| # | Phase | Decision | Classification | Principle |
|---|-------|----------|----------------|-----------|
| 38 | RE-ENG | Stage the deliverable: artifact v1 frozen end of week 6 | Mechanical | P6 |
| 39 | RE-ENG | Honest effort accounting; cut order = sport or model, never artifact or tests | Mechanical | P1 |
| 40 | RE-ENG | Census validation gate to week 2, first 200 games | Mechanical | P1 |
| 41 | RE-ENG | T4 re-estimated at 23 rows; 7 P1 required for December | Mechanical | P3 |
| 42 | RE-ENG | Deterministic pre-game ratings as a fixed covariate | Mechanical | P5 |
| 43 | RE-ENG | ToS check to week 1; E18 promoted to P1 | Mechanical | P1 |
| 44 | RE-ENG | Dev dress rehearsal before the holdout opens | Mechanical | P1 |
| 45 | RE-ENG | Collector split across week 4 and week 7 | Mechanical | P1 |
| 46 | RE-ENG | Collector scheduling written back into Phase 6 and CI/CD | Mechanical | P1 |
| 47 | RE-ENG | T9 to P1, strata expanded, estimate corrected to 12-20h | Mechanical | P1 |
| 48 | RE-ENG | Status line and report verdict reconciled | Mechanical | P5 |
| 49 | RE-ENG | Snapshot corrected to end of census (week 3) | Mechanical | P5 |
| 50 | RE-ENG | Availability pre-registration as a separate later-hashed addendum | Mechanical | P1 |
| 51 | RE-ENG | Per-sport exclusion arithmetic shown | Mechanical | P1 |
| 52 | RE-ENG | NHL rejustified by headline-2 per-stratum n | Mechanical | P1 |
| 53 | RE-ENG | Within-season volume deciles to de-confound liquidity | Mechanical | P1 |
| 54 | RE-ENG | Noise-floor simulation at per-stratum n | Mechanical | P1 |
| 55 | RE-ENG | 2x2 strata, min 150 games/bin, slope-difference as primary | Mechanical | P5 |
| 56 | RE-ENG | Bootstrap resamples games, not rows | Mechanical | P1 |
| 57 | RE-ENG | Volume definition frozen with a content hash | Mechanical | P1 |
| 58 | RE-ENG | Family-wise policy mandatory for headline 2 | Mechanical | P1 |
| 59 | RE-ENG | "Cannot come back empty" corrected to "a measurement, not a finding" | Mechanical | P5 |
| 60 | RE-ENG | Eng tasks E1-E20 written into the plan (were JSONL-only) | Mechanical | P1 |

**Running total: 60 auto-decisions.** 57 mechanical, 3 taste (#8 E4 snapshot, #9 E1 dataset
release, #11 E3 GBM ceiling). Both User Challenges were resolved by the user, not
auto-decided. One previously-escalated taste item (dev/holdout split) was retired by
decision #24.

## Cross-Phase Themes

**Theme: the integrity gate is broken** — flagged independently in the spec-review round
(noise-floor arithmetic), the CEO phase (subagent finding 11, "a kill switch calibrated to
false-fire"), and the eng phase (R3, "conflates pipeline validation with the project's own
finding"). Three independent passes, three different arguments, same conclusion.
**High-confidence signal.** Resolution escalated from "split the gate" to "remove its gate
authority entirely" (decision #23).

**Theme: the forward collector is the weakest component** — CEO phase (subagent finding 4,
decouple it) plus eng phase (R4 no named data source, R5 alerting cannot fire, R13
unaffordable on Actions). Four findings across two phases converge on the same component.
**High-confidence signal.**

**Theme: the rolling pre-game state is the right model** — CEO subagent finding 12 and eng
R7 arrived at option (a) independently, by different routes (domain realism vs the
arithmetic of a 2-season random walk). **High-confidence signal**, and it retired a gate item.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 (via autoplan) | clean | 13 findings, 8 critical gaps, 1 premise falsified — all dispositioned |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | skipped | codex binary not installed |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 (initial + re-review) | clean | 17 + 22 findings, 23 test gaps — all dispositioned |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | skipped | no UI scope (1 false-positive match) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | skipped | no developer-facing scope (3 false-positive matches) |

- **CROSS-MODEL:** not available. Codex absent, so both phases ran `[subagent-only]`. In
  place of a second model, four findings were settled by live API probe rather than by
  agreement: the 2023-24 dead-market window, the two-token row count, the absent volume
  field, and the ET-date convention across DST.
- **VERDICT:** CEO + ENG reviewed, plus a focused Eng re-review of the amended plan (22
  further findings). Both User Challenges RESOLVED by the user: Challenge 1 rejected
  (Approach B stands), Challenge 2 accepted (miscalibration is a co-headline). 60 decisions
  auto-decided and logged. **CEO + ENG CLEARED — ready to implement.** All 3 taste items
  confirmed by the user (E1 dataset release, E3 GBM ceiling, E4 snapshot-first all kept).

NO UNRESOLVED DECISIONS
