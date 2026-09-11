<!-- /autoplan restore point: /Users/arva/.gstack/projects/Chira/main-autoplan-restore-20260911-160417.md -->
# Chira — Implementation Plan

Branch: main
Design doc: [docs/designs/chira-market-calibration-engine.md](docs/designs/chira-market-calibration-engine.md)
Status: DRAFT, awaiting review

## Goal

An interpretable, cross-sport win-probability engine benchmarked against Polymarket
closing prices. NBA and NHL. The claim is calibration, not profit: how well-calibrated is
a model trained only on public schedule and team data, measured against a real-money
market that prices $1M-$2M per game.

Portfolio artifact first. The output is a published writeup with charts, not just a repo.

## Non-negotiable constraints

- **Interpretability vetoes model classes.** Additive and legible only. A gradient-boosted
  ensemble at 0.18 Brier fails this spec; a hierarchical logistic at 0.20 passes it.
- **The market price is banned from the headline model** and required only for the nested
  test's Model B. Separate code paths, price physically absent from the standalone feature
  table.
- **Moneyline only.** Spreads and totals out of scope.
- **Pre-registration is committed before the first model fit.** The git hash is the
  timestamp.

## Phase 0 — Foundations

- [ ] `uv` project, Python 3.12. Dependencies: `requests`, `duckdb`, `numpyro`,
      `matplotlib`, `nba_api`.
- [ ] HTTP layer: on-disk response cache, rate limiter with fixed delay, exponential
      backoff on 429, resumable state so a block mid-census is not fatal.
- [ ] `PREREGISTRATION.md` committed. Contents fixed in the design doc: sealed holdout,
      Brier primary with log loss clipped to [0.01, 0.99], one designated primary test,
      home-side-only calibration convention, Clark-West with date-block bootstrap, the
      numeric integrity gate, risk tiers at [0.02,0.05)/[0.05,0.10)/>=0.10, dev-side
      rolling-origin protocol, two closing-price constructions.
- [ ] **Open item, blocks the gate:** re-derive the integrity thresholds against the
      estimator's noise floor by simulation. See Reviewer Concerns in the design doc. The
      currently written ECE and per-bin tilt caps sit at or below sampling noise and would
      fail a working pipeline.

## Phase 1 — Coverage census (the project gate)

Answers whether the project is viable, and in which sport.

- [ ] Learn the abbreviation map first, **PER SEASON** — the convention is not stable across
      seasons (`nba-lal-no-2023-12-07` uses `no` for New Orleans where 2025 uses `nop`).
      Probe ~3 known games per team per season (32 teams x 3 ≈ 96 requests per sport-season)
      via `/events?slug=`. Do NOT guess. Confirmed within-season irregulars: `sj` not `sjs`,
      `mon` not `mtl`, `cal` not `cgy`, `tb` not `tbl`, bare `utah`.
- [ ] Build slugs `<sport>-<away>-<home>-<YYYY-MM-DD>` from **US-Eastern schedule dates**
      taken directly from `nba_api` `GAME_DATE` and the NHL schedule's `gameDate`. Never
      derive ET from `gameStartTime`; if converting, `America/New_York` with DST, never a
      fixed offset.
- [ ] Enumerate from the schedule, never by paginating Gamma. `/markets` caps `limit` at
      100 and returns nothing past `offset ~2100`.
- [ ] **Seasons 2024-25 and 2025-26 ONLY** (two seasons). 2023-24 is EXCLUDED: probed Dec-2023
      NBA markets carry $6/$0/$0/$0 volume and Mar-2024 has zero sports slugs, so those
      prices are not calibrated probabilities. **Do not "fix" the missing season later.**
      ~2,460 NBA games and ~2,624 NHL games. Per game: 1 `/events?slug=` + 2
      `prices-history` = 3 requests, so **~7,400 NBA + ~7,900 NHL ≈ 15,300 requests**,
      plus ~400 abbreviation-map probes.
- [ ] **Report the two seasons separately as well as pooled.** Per-game liquidity quadrupled
      between them (~$500k in 2024-25 vs ~$1.9M in 2025-26), so they are two different market
      regimes and price sharpness is not constant across them.
- [ ] Per game, store `outcomePrices` (free label), `gameStartTime`, volume, and the
      minute-level series via `prices-history?market=<tokenId>&startTs=<unix>&fidelity=1`.
      Extract close, T-1h, T-6h, T-24h.
- [ ] Assert `abs(p_home + p_away - 1) < 1e-6` and fail loudly. The complementarity
      invariant is verified on 3 games and load-bearing enough to be enforced.
- [ ] Classify every miss as "no market exists" vs "slug variant not tried." Exclude
      `["0.5","0.5"]`, unresolved, and UMA-disputed markets from scoring and count them on
      a reconciliation line.

## Phase 2 — The two gate charts

- [ ] **Chart 1: coverage by week of season**, stacked with/without market, per sport, plus
      a median-volume panel. Decides whether the project proceeds and which sport is
      primary.
- [ ] **Chart 2: the market's own calibration curve.** Home side only, one observation per
      game, equal-count or LOESS bins with bootstrap bands, Murphy decomposition of Brier
      into reliability, resolution and uncertainty. Checked against the pre-registered
      integrity thresholds. This is both the benchmark line and a pipeline self-test: if a
      real-money market does not come out near-calibrated, the label join or the
      closing-price extraction is broken.
- [ ] **Write the one-paragraph answer: which sport is the better primary, and why.**

## Phase 3 — Ingestion and feature store

- [ ] DuckDB store. Game key: `nba_api` `GAME_ID` joined to Polymarket `conditionId` via
      an explicit, auditable join table keyed on (sport, ET date, away abbr, home abbr).
- [ ] Price table grain: one row per token per minute, ~69M rows across three seasons and
      two sports.
- [ ] **Point-in-time correctness enforced structurally.** Every feature query takes a
      mandatory `as_of`; no unqualified read path exists in the API. Regression test: a
      query with `as_of=T` returns byte-identical results against a DB truncated at T and
      a DB holding all later rows.
- [ ] Features, historical half: schedule, rest days, back-to-backs, travel distance,
      prior-game results with known completion times. **Nothing availability-derived** —
      see the blocker.

## Phase 4 — Model

> **BLOCKING DECISION, surfaced by the two-season finding.** Sealing 2025-26 as the holdout
> leaves exactly ONE dev season (2024-25), so the pre-registered **rolling-origin dev
> protocol across seasons is impossible**. Resolve before writing numpyro code. Candidates:
> (a) a rolling pre-game team-strength state (Elo-like / state-space) updated game by game,
> which needs no season intercepts, removes the holdout identifiability hole entirely, and
> better models a domain where strength moves within a season; (b) within-season splits,
> holding out the last 20% of each season; (c) keep team-season intercepts plus the mandatory
> random walk and accept a single dev season. Recommended: (a). This is a taste decision
> escalated to the Final Gate.

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
- [ ] Run the nested test under **both** closing-price constructions (last value, and
      trailing-15-minute VWAP). A gain existing only under the last-trade construction is
      measurement error in the benchmark.
- [ ] Risk tiers reported with frequency, hit rate, calibration and bootstrap intervals per
      pre-registered bucket. State expected top-tier shrinkage up front.

## Phase 6 — Forward collector (parallel, from late October 2026)

The only path to the availability hypothesis.

- [ ] **Poll every 5-10 minutes across the daily game window**, or trigger one run per game
      from that day's schedule. A nightly job captures nothing that deserves the name
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
- [ ] **Pre-register the availability test on the status-change subset with a minimum-n
      gate.** Power: 200-400 status-change games gives a paired-Brier SE near 0.0015-0.002
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

- [ ] GitHub Actions: tests and lint on push.
- [ ] Separate scheduled workflow for the Phase 6 collector, per-game or short-interval.
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
| Neural representation transfer | Vetoed by the interpretability constraint |
| Paid data vendors | Unnecessary; the free API returns full minute history (vendor claim to the contrary is false) |

### SELECTIVE EXPANSION — cherry-pick decisions (auto-decided)

| # | Expansion | Effort (human / CC) | Decision | Principle |
|---|---|---|---|---|
| E1 | Publish the census as a documented public dataset release | ~4h / ~20min | **ACCEPTED** | P1, P2 |
| E2 | Stratify the calibration curve by liquidity and time-to-close | ~3h / ~15min | **ACCEPTED** | P1, P2 |
| E3 | Fit a GBM as a reported benchmark *ceiling*, not a shipped model | ~1d / ~30min | **ACCEPTED** | P1 |
| E4 | Immutable snapshot release in week 1; all phases run against it | ~3h / ~15min | **ACCEPTED** | P2 |
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
- [ ] **T4 (P1, human: ~4h / CC: ~25min)** — tests — Build the 10-row test plan from Section 6, 3 designated P1
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
- [ ] **T7 (P2, human: ~3h / CC: ~15min)** — ingest — Snapshot to an immutable Parquet release in week 1; all phases read the snapshot
  - Surfaced by: Section 1 F2 — one unauthenticated third-party endpoint, no contract, multi-month project
  - Files: ingest/snapshot.py, .github/workflows/release.yml
  - Verify: every downstream phase runs with the network disabled
- [ ] **T8 (P2, human: ~4h / CC: ~20min)** — scoring — Split the integrity gate into hard invariants and descriptive reporting
  - Surfaced by: Section 8 / Reviewer Concerns — thresholds sit at or below the estimator noise floor and will false-fire
  - Files: scoring/integrity.py, PREREGISTRATION.md
  - Verify: simulated perfectly-calibrated market passes the hard gate; ECE/slope/tilt report against simulated noise bands
- [ ] **T9 (P2, human: ~4h / CC: ~20min)** — scoring/charts — Stratify the calibration curve by liquidity and time-to-close
  - Surfaced by: 0C-bis Approach C + literature (arXiv 2602.19520: bias concentrated in specific categories)
  - Files: scoring/calibration.py, charts/calibration.py
  - Verify: per-stratum curves with bootstrap bands; 2024-25 vs 2025-26 reported separately
- [ ] **T10 (P2, human: ~2h / CC: ~10min)** — scoring — Hostile-QA synthetic-market test of the scorer
  - Surfaced by: Section 6 — the instrument is never validated before it judges the market
  - Files: tests/test_scorer_synthetic.py
  - Verify: perfectly-calibrated synthetic → near-zero miscalibration; deliberately tilted → caught, correct sign
- [ ] **T11 (P2, human: ~4h / CC: ~20min)** — docs — Publish the census as a documented dataset release
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
