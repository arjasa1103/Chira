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

- [ ] Learn the abbreviation map first. Probe ~3 known games per team (32 teams x 3 ≈ 96
      requests per sport) via `/events?slug=`. Do NOT guess. Confirmed irregulars: `sj`
      not `sjs`, `mon` not `mtl`, `cal` not `cgy`, `tb` not `tbl`, bare `utah`.
- [ ] Build slugs `<sport>-<away>-<home>-<YYYY-MM-DD>` from **US-Eastern schedule dates**
      taken directly from `nba_api` `GAME_DATE` and the NHL schedule's `gameDate`. Never
      derive ET from `gameStartTime`; if converting, `America/New_York` with DST, never a
      fixed offset.
- [ ] Enumerate from the schedule, never by paginating Gamma. `/markets` caps `limit` at
      100 and returns nothing past `offset ~2100`.
- [ ] Seasons 2023-24 through 2025-26, both sports. ~3,900 NBA games and ~4,100 NHL games,
      plus one `prices-history` call per token: **~11,000-12,000 requests per sport,
      20,000+ total.**
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

- [ ] Hierarchical logistic in `numpyro`. Non-centered parameterization, R-hat and
      divergence diagnostics, posterior predictive checks.
- [ ] **Pool team-BY-SEASON effects** (J ≈ 90 NBA, ≈ 96 NHL). Pool the team-season
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
