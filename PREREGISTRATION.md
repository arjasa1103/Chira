# Pre-Registration — Chira

Committed **before the first model fit**. The git hash of this file is its timestamp.
Amending it later is permanently visible in history, which is the point.

**Scope of this document:** the historical (backtest) half only. The availability /
forward-capture experiment is deliberately NOT pre-registered here; it gets a separate,
later-hashed addendum committed only if and when its data source is proven (see §9).

---

## 1. Data

- **Usable seasons: 2024-25 and 2025-26 only.** 2023-24 is excluded on evidence, not
  preference: probed Dec-2023 NBA markets carry $6/$0/$0/$0 volume and Mar-2024 returns zero
  sports slugs. A market with no trading has no price, so it cannot be a calibrated
  probability. This exclusion is final and must not be "fixed" later.
- **Sports:** NBA and NHL. Moneyline (game winner) only. Spreads, totals and props are out.
- **Expected size:** ~2,460 NBA + ~2,624 NHL games, ~5,084 total.
- **Regimes are not pooled silently.** Per-game liquidity roughly quadrupled between the two
  seasons (~$500k in 2024-25 vs ~$1.9M in 2025-26). Every headline number is reported per
  season as well as pooled.
- **Snapshot.** All modeling and scoring run against an immutable Parquet snapshot taken at
  the end of the census, never against the live API. Labels are frozen in it with a content
  hash, because Gamma metadata is mutable when UMA disputes resolve.

## 2. Closing price

- **Primary definition:** the home-side token's last `prices-history` value at or before
  `gameStartTime`, at `fidelity=1` (documented as minutes).
- **Second construction: the T-1h value.** A trailing-window VWAP was considered and
  **removed as not computable**: `prices-history` points carry only `{t, p}` with no volume
  field, so there are no weights. The choice of T-1h over a trailing average is also
  empirical: **41% of sampled games (53/128) show a flat run of >= 10 identical pre-tipoff
  minute values**, i.e. carry-forward, so a trailing average would usually equal the last
  value and could not detect the measurement error it exists to detect.
- Every nested-test result is reported under **both** constructions. A gain that exists only
  under one is measurement error in the benchmark, not market inefficiency.
- **Staleness is reported, never silently dropped.** Games with a flat run >= 10 are flagged
  and reported as a sensitivity split.
- **Calibration side convention: home only, one observation per game.** The two outcome
  tokens are exact complements (verified: last pre-tipoff values summed to 1.0000 on every
  probed game, and the ingestion layer asserts `|p_home + p_away - 1| < 1e-6` and fails
  loudly). Plotting both sides would double-count every game and force artificial symmetry
  about 0.5, hiding the very asymmetry the chart exists to show.

### Amendment 1 (2026-09-13): the tipoff time the closing price is cut at

**Changed.** The primary definition above cuts at Polymarket's `gameStartTime`. It now
cuts at the **league's own start time** (NHL `club-schedule-season.startTimeUTC`; NBA
`scheduleleaguev2.gameDateTimeUTC`), falling back to `gameStartTime` only where the league
source has no time, with the fallback recorded per game in `priced.cutoff_source`. The
T-1h, T-6h and T-24h looks are measured from the same cutoff.

**Why.** `gameStartTime` is supplied by the party being benchmarked. On the first full
week-3 census it disagreed with the league by more than 15 minutes on **69 priced games**
(21 NBA, 48 NHL), measured against every priced game in all four sport-seasons:

- **24 were LATE** (15 NBA, 9 NHL), which admits in-game and settled quotes into the
  "closing" price. The worst was 360 minutes late (NBA 2025-26). In the week-2 slices one
  NBA 2024-25 market, `nba-dal-uta-2024-11-14`, stored a close of 0.9995 on a 115-113 game.
- **45 were EARLY** (6 NBA, 39 NHL), which cuts the close well before real tipoff. Of the
  NHL 2025-26 cases, 36 are exactly 240 minutes early (7 games, October 2025, daylight
  time) or 300 minutes early (29 games, November 2025, after daylight time ended): an
  Eastern wall-clock time recorded as UTC.

The interim ET-hour plausibility rule passed all of those, because a 4- or 5-hour error
still lands inside 11:00-23:00 ET. It also rejected 6 games outright: 5 more November 2025
NHL games at exactly 300 minutes early, and a genuine 09:00 ET NHL game played in Stockholm
(`nhl-nsh-pit-2025-11-16`, neutral site), whose Gamma time was correct.

**What is preserved.** The intent of the definition, the last value at or before real
tipoff, is unchanged. The value under the original definition is still computed for every
game as `priced.p_home_close_gamma`, with the disagreement in `priced.gamma_delta_min`, so
any result can be re-run under the pre-registered cutoff and the difference reported.

**When, and what had been seen.** Adopted before any model fit and before any calibration
statistic was computed on the census. It was chosen from timestamp disagreement alone,
never from outcomes. For full disclosure: Brier, ECE and a calibration slope were computed
once on a 199-game week-2 slice as a README illustration. That slice is not part of any
pre-registered analysis, and no statistic on it informed this change.

**Not an amendment, recorded for completeness.** Markets are now selected by
`sportsMarketType == "moneyline"`. Moneyline-only was always the definition (PLAN.md,
section 1 here), but the implementation had taken the first market whose outcome labels
matched the two teams, which priced 5 NHL 2025-26 spread markets as moneylines. That was
a bug against the pre-registered definition, not a change to it.

Also not an amendment: how the complementarity assertion (`|p_home + p_away - 1| < 1e-6`)
is evaluated. The two tokens' price series are sampled independently: at identical
timestamps in 2024-25, but a median 5 s and a p90 59 s apart in 2025-26. Comparing each
token's own last pre-tipoff point therefore compared different moments, and produced 2 NHL
failures on markets whose simultaneous quotes all summed to exactly 1. The assertion is now
applied to every simultaneous pair in the last 2 hours before the cutoff (each home quote
with the latest away quote at most 60 s before it), and a game passes when at least half of
those pairs satisfy it. On the full census every game had at least 74 pairs; the lowest
share on any game was 0.5755, and the largest per-pair error 0.03 (price movement between
samples). A market that is not a true complement fails at every pair. Tolerance, side
convention and every analysis quantity are unchanged; per-game evidence is stored as
`complement_share` and `complement_pairs`.

## 3. Metrics

- **Primary: Brier score.** Log loss is secondary, with probabilities clipped to
  **[0.01, 0.99]**; unclipped log loss is unbounded, so one mis-joined label at an extreme
  price would silently decide the result. No hypothesis test is attached to log loss.
- Murphy decomposition (reliability - resolution + uncertainty) reported alongside, and
  asserted to reconcile with the direct Brier.
- Reliability diagrams use **equal-count bins** with game-level bootstrap bands.

## 4. Integrity gate — derived from simulation, not intuition

The gate exists to catch a broken pipeline. A threshold below the estimator's own sampling
noise rejects a *correct* pipeline, which is the worst failure this gate can have.

A null distribution was simulated (4 significant figures, 1,500 replicates per n) by
bootstrapping prices from a **measured** 128-game empirical distribution of NBA home closing
prices and drawing outcomes as `y ~ Bernoulli(p)` — perfectly calibrated by construction.

**Null behaviour of a PERFECTLY calibrated market** (10 equal-count bins):

| n | ECE p95 | ECE p99 | max-bin-dev p99 | slope 95% CI | intercept 95% CI |
|---|---|---|---|---|---|
| 150 (one bin) | 0.1289 | 0.1454 | 0.3941 | [0.66, 1.50] | [-0.41, 0.36] |
| 850 (one stratum) | 0.0544 | 0.0620 | 0.1669 | [0.83, 1.17] | [-0.15, 0.15] |
| 1,230 (one season) | 0.0451 | 0.0520 | 0.1417 | [0.87, 1.15] | [-0.13, 0.12] |
| 2,460 (NBA both) | 0.0317 | 0.0362 | 0.0991 | [0.90, 1.10] | [-0.09, 0.09] |
| 5,084 (both sports) | 0.0226 | 0.0260 | 0.0713 | [0.93, 1.07] | [-0.06, 0.06] |

**Earlier draft thresholds are hereby withdrawn as unusable.** An ECE cap of 0.02 false-fires
at every n tested, including by 2.7x at per-stratum n and 6.4x at per-bin n. A per-bin
deviation cap of 0.03 false-fires everywhere. A slope window of [0.90, 1.10] is sound at
n >= 2,460 but too tight at per-stratum n.

**Adopted gate — evaluated on the FULL census (n ~ 5,084), never on the holdout.**

**Every bound is rounded OUTWARD from the simulated null.** A first draft rounded to two
decimals in whichever direction was tidier, which put three of four thresholds *inside* the
null distribution they were derived from — re-creating the exact false-fire defect this
simulation existed to remove. The intercept was the worst: band `[-0.06, 0.06]` against a
null 95% CI of `[-0.0612, 0.0640]`, so a perfectly calibrated market failed by construction.

| Check | Null (n=5,084) | Adopted threshold | Direction |
|---|---|---|---|
| ECE | p99 = 0.0260 | <= **0.03** | outward |
| max per-bin deviation | p99 = 0.0713 | <= **0.08** | outward |
| Cox slope 95% CI | [0.9305, 1.0703] | within **[0.93, 1.08]** — **superseded, see Amendment 2** | outward |
| Cox intercept 95% CI | [-0.0612, 0.0640] | within **[-0.07, 0.07]** | outward |

These live in `chira.constants` as `GATE_ECE_MAX`, `GATE_MAX_BIN_DEV`, `GATE_SLOPE_BAND`,
`GATE_INTERCEPT_BAND`, and `tests/test_week1_facts.py::TestNoiseFloorIsRespected` asserts each
one sits at or above the simulated null. Changing either the gate or the estimator fails the
suite, so this table cannot drift from the code.

**Pool caveat.** The null was bootstrapped from a measured NBA-only pool (n=128). NHL prices
are markedly more concentrated (83% inside [0.35, 0.65] vs NBA's 41%; E[p(1-p)] 0.2395 vs
0.1970), and the pooled NBA+NHL null is slightly wider: ECE p99 0.0264 vs 0.0261. The
adopted outward-rounded bounds cover both, but the pool must be re-measured once real NHL
census prices exist, and the NHL-only band re-derived rather than inherited.

### Amendment 2 (2026-09-16): the Cox slope band, re-derived from the real pool

**Changed.** `GATE_SLOPE_BAND` widens from **[0.93, 1.08]** to **[0.91, 1.10]**. The other
three adopted bounds are unchanged.

**Why.** This discharges the pool caveat directly above, which required the null to be
re-measured once real NHL prices existed. Re-simulated on the census's own closing prices
(`scripts/derive_null_bands.py`, 1,500 replicates, outcomes drawn `y ~ Bernoulli(p)` so the
market is perfectly calibrated by construction), the pooled null 95% CI for the Cox slope is
**[0.9183, 1.0908]**, which escapes the adopted [0.93, 1.08] at both ends. Since section 4
states the bound as an *equivalence* test — the CI must lie entirely inside the band — a
perfectly calibrated market would have failed it. That is the exact false-fire defect this
simulation exists to prevent, so the bound is re-rounded outward to [0.91, 1.10].

Two independent causes, both of which the week-1 derivation could not have known:

- **The real pooled pool is more concentrated than the NBA-only pool it was built from.**
  Measured: E[p(1-p)] 0.2162 pooled (NBA 0.1971, NHL 0.2375) against the 0.1970 assumed, and
  60.5% of pooled closes inside [0.35, 0.65] (NBA 40.5%, NHL 82.6%) against 41%. Mass near
  0.50 is where Bernoulli variance is highest, so the null widens. The caveat's *predictions*
  were accurate — it guessed NHL at 83% and 0.2395 — it simply had no census to bind them to.
- **The operative n is 4,661, not 5,084.** The week-1 table assumed every scheduled game
  would be priced; 423 are classified misses. Fewer observations widen the null again.

**What did NOT change, and why each still holds outward:** ECE cap 0.03 against a re-measured
p99 of 0.0272; max per-bin deviation 0.08 against 0.0729; Cox intercept [-0.07, 0.07] against
a re-measured null CI of [-0.0606, 0.0620]. All three still sit outside the null they govern.

**No reported result changes.** The four chart-2 slope CIs measured at the close are
NBA 2024-25 [0.864, 1.130], NBA 2025-26 [0.914, 1.193], NHL 2024-25 [0.754, 1.322] and
NHL 2025-26 [0.513, 1.082]. Every one falls outside both the old and the widened band, so
the amendment flips no verdict and cannot be manufacturing a pass. Widening a bound after
seeing data is the move this document exists to make visible, so: the re-derivation used
**prices and n only**, never an outcome, and the breach is computable without looking at who
won. The chart-2 statistics were computed in the same week-4 session, and none of them
informed this change.

**Where the numbers live.** `chira.constants.CENSUS_NULL_*`, with
`tests/test_week1_facts.py::TestNoiseFloorIsRespected` asserting each adopted bound covers
the re-measured null. That guard test previously simulated a `uniform(0.1, 0.9)` pool, which
is *less* concentrated than the census and is why it never caught this. It now asserts
against the measured census numbers.

**Per-stratum reference, required by the rule below.** Per-season and per-sport n values run
well above the pooled ECE cap and must never be judged against it — for example the null ECE
p99 is 0.0515 at NBA n=1,226 and 0.0655 at NHL n=896, against 0.0272 pooled. The per-n rows
are recorded in `CENSUS_NULL_ECE_P99_BY_N` and in notes/week4-charts.md.

Stated as an **equivalence** test: the CI must lie *entirely within* the band, so an
imprecise estimate fails. "CI contains 1.0" is accept-the-null testing and would let noisy
data pass while punishing precise data.

**Per-stratum and per-bin analyses use the corresponding row of the table above**, never the
n=5,084 numbers.

**The market's calibration has NO gate authority.** An earlier draft said "if a real-money
market does not come out near-calibrated, the pipeline is broken." That inference is invalid:
a miscalibrated result is ambiguous between a defect and headline 2's actual finding, and the
literature reports bias concentrated in specific categories. Pipeline validity is established
only by checks that do not assume the market is calibrated:

1. **Label agreement** — the resolved `outcomePrices` winner must equal the `nba_api`
   box-score winner, and the nickname at the `p_home` index must map to the slug's home
   abbreviation. **100% agreement required.** Already run in week 1: **128/128 agree.**
2. **Complementarity** — `|p_home + p_away - 1| < 1e-6`, asserted at ingest, fails loudly.
3. **Reconciliation** — `scheduled == priced + misses`, with every miss carrying a reason
   enum and the full set of attempted slugs. Fault-injection test asserts the assert fires.
4. **Shuffled join** — permuting the join table must collapse measured calibration.
5. **Synthetic scorer** — a perfectly calibrated synthetic market must score near zero
   miscalibration; a deliberately tilted one must be caught with the correct sign.
6. **Non-JSON 200** — a WAF challenge page must raise, never be recorded as `no_market`.

## 5. Model

**Pre-committed now, because "Elo-like / state-space" spans two cost classes and only one
fits the schedule.**

- **Team strength enters as a DETERMINISTIC pre-game rating, computed outside the model and
  supplied as a fixed covariate.** Not a latent random walk. A latent per-team-per-game walk
  is ~75k latent variables on ~5k observations, and with divergences treated as hard failures
  it does not fit in the available weeks. The deterministic form preserves interpretability
  and keeps MCMC cheap.
- On top of that: a hierarchical logistic with **partially pooled team-season intercepts and
  home advantage**. Rest, back-to-back and travel stay **global** (unpooled): NBA teams see
  ~14 back-to-backs a season, which cannot support team-specific coefficients.
- Sport enters as a fixed effect. J = 60 (NBA) and 64 (NHL) team-seasons across two seasons.
- **Interpretability is a hard constraint that vetoes model classes.** A gradient-boosted
  ensemble scoring 0.18 Brier FAILS this spec; an additive decomposition at 0.20 PASSES it.
  A GBM is fit **only as a reported benchmark ceiling**, never shipped, to convert
  "interpretability is worth a Brier cost" from an assertion into a measured number.
- Hyperprior sensitivity analysis is mandatory and reported. On hierarchical variance
  parameters the prior can be the result.
- MCMC diagnostics are **hard failures**: any divergence or R-hat > 1.01 raises. A quietly
  non-converged posterior produces a real-looking Brier score, which is worse than a crash.

## 6. Splits

- **Sealed holdout: the 2025-26 season.** Opened exactly once, after the model is frozen by
  commit. A full dress rehearsal on dev must first produce every table and figure that will
  appear in the writeup, so opening the holdout only fills in numbers.
- **Dev: 2024-25**, with rolling-origin evaluation *within* the season. Cross-season rolling
  origin is impossible with one dev season, which is why §5 pre-commits to a pre-game state
  that needs no cross-season intercept projection.
- Clark-West is never computed on dev data.
- **Regime caveat, pre-stated:** dev is the thin season (~$500k/game) and holdout is the sharp
  one (~$1.9M/game). Market Brier is reported on dev and holdout side by side so the
  model-vs-market gap is never confused with the regime difference.

## 7. Nested test

- **Model A:** market price only. **Model B:** market price + features.
- **Statistic: Clark-West MSPE-adjusted.** NOT Diebold-Mariano: under the null the two nested
  forecasts are identical in population, the loss differential is degenerate, and DM's normal
  reference distribution does not apply.
- **Scheme:** fixed, one estimation window on dev, a single pass over the sealed holdout.
- Critical values by **block bootstrap on calendar date** (errors cluster by date and team),
  with the analytic normal p-value reported alongside. The block count will be reported;
  with ~170 game dates in a season a stationary bootstrap is used instead of fixed blocks.
- B is reported against **both** nulls: the identity market price, and a fitted recalibration
  `a + b·logit(p)`. For the latter, B must literally nest it (`B = a + b·logit(p) + f(x)`
  with free `a, b`) or CW does not apply. Winning only against the identity null is a
  recalibration finding about a public tilt, not evidence of private information.
- **One primary test, alpha = 0.05: Model B vs the recalibration null, NBA, Brier.**
  Every other comparison (other sport, other metric, other null, per-tier) is labeled
  exploratory. Without this, 2 nulls x 2 sports x 2 constructions x per-tier reporting has
  no family-wise control.

## 8. Headline 2 — stratified market calibration

- **Strata: a pre-registered 2x2** — 2 liquidity levels x 2 season phases. Liquidity is cut
  on **within-season volume deciles**, not pooled across seasons: pooling would make
  "low liquidity" and "2024-25" the same cut, since the seasons differ ~4x.
- Volume is terminal cumulative market volume. It is outcome-correlated (close games attract
  volume) and mutable, so the definition is frozen in the snapshot with a content hash and
  the selection caveat is reported.
- **Minimum 150 games per probability bin**, merging bins upward when short. Ten equal-count
  bins at ~85 games/bin gives SE ~0.054, and the tail bins where the literature reports bias
  would hold a handful of games each.
- **Single primary directional test: the difference in Cox calibration slope between strata.**
  A grid of curves across ~24 cells produces a "finding" by construction; everything beyond
  the primary test is exploratory.
- Bootstrap resamples **games, not rows.** Time-to-close (close, T-1h, T-6h, T-24h) is a
  repeated measure — four looks at one sample — so row-level resampling gives bands that are
  too narrow.
- **Honest framing:** this guarantees a *measurement*, not a *finding*. Under the n
  constraints above, wide overlapping bands are a plausible outcome and will be reported as
  such rather than mined for significance.

### Amendment 3 (2026-09-20): the headline-2 strata, rebuilt

Three changes to section 8, all adopted before any stratified statistic was computed, and
all forced by measurements that did not exist when section 8 was written.

**3a. Liquidity is cut WITHIN season phase, not within season.** Section 8 cuts volume
deciles within season to stop "low liquidity" from meaning "2024-25". That defends against
the between-season confound and does nothing about the within-season one. Measured on the
census (`week_of_season` against terminal volume, games with volume present):

| Sport-season | Spearman(volume, week) | Low-liquidity games that are early, as pre-registered |
|---|---|---|
| NBA 2024-25 | +0.521 | 0.686 |
| NBA 2025-26 | +0.361 | 0.660 |
| NHL 2024-25 | +0.532 | 0.719 |
| NHL 2025-26 | +0.413 | 0.695 |

0.500 would mean the two axes are independent. At 0.69 they are close to the same cut, and
section 8's primary directional test is the slope difference BETWEEN strata, so the
confound lands directly on the headline. Cutting volume inside each phase restores
0.511 / 0.503 / 0.506 / 0.534 and evens the cells (221-312 per cell, against 126-419).
The stratum now reads "low liquidity *relative to that point in the season*", which is the
quantity section 8 intended.

A residual-based alternative (regress log volume on week, stratify on the residual) was
tested and works comparably (residual-vs-week correlation at most 0.07). It was not adopted:
it buries a fitted model inside a pre-registered definition, for no measured gain.

**3b. The primary directional test is NBA-only. NHL is reported as a contrast case.**
PLAN.md made NHL load-bearing for per-stratum n, and n is fine (896 and 1,310 priced). What
that reasoning could not anticipate is that the NHL market carries almost no information.
Murphy resolution at the close, measured in week 4:

| | NBA | NHL |
|---|---|---|
| 2024-25 | 0.04831 | 0.01520 |
| 2025-26 | 0.05201 | 0.00571 |

A market that quotes near the base rate is perfectly calibrated and uninformative, and it
cannot be shown to be miscalibrated in an interesting way at any n. NHL closes also span
0.200-0.825 with 82.6% inside [0.35, 0.65], so the favourite and longshot tails where the
literature reports bias are nearly empty. NHL is therefore reported in full, as the contrast
case that a calibrated market need not be a useful one, and is not the sample the primary
test is computed on. This narrows the primary test; it does not drop data or hide a result.

**3c. Where market-level volume is absent, event-level volume is used as a flagged proxy.**
318 priced games carry no volume: 161 NBA and 157 NHL between 2026-03-04 and 2026-03-25,
plus 8 NBA on 2024-11-12/13. Confirmed against the live API on 2026-09-19 rather than
inferred: for games in that window the Gamma market object carries **no** volume field at
all, while a 2025 market carries nine (`volume`, `volumeNum`, `volumeClob`, and the 1wk/1mo/1yr
variants). In the affected window 161 of 170 NBA and 157 of 167 NHL priced games are hit, so
it is an upstream gap in a calendar block, not a code path in one sport.

The block is **late-season** (weeks 20-23 NBA, 22-25 NHL of 25 and 28), so dropping those
games would silently delete late-season, disproportionately high-volume games and
re-introduce by the back door exactly the season-phase confound 3a removes.

Adopted: where the market carries no volume, use the **event-level** volume, recorded per
game with a provenance flag (`volume_source`). In a 24-game sample, 15 had event-level
volume and 9 had none. Games with neither stay out of the liquidity strata and are reported
as a named, counted category with their dates.

This is a definition change and is stated as one: event volume sums **every market type in
the event** (moneyline, spread, first-half), so it is not the pre-registered per-market
moneyline volume. It is therefore an upper bound on the quantity section 8 defines, it is
used only where the real value does not exist, every affected game is flagged, and the
primary test is re-run with all proxied games excluded as a mandatory sensitivity check. If
the two disagree, the excluded-games version is the reported one.

**When, and what had been seen.** Adopted before any stratified statistic, any bootstrap
band, and any model fit. Full disclosure, because this is the one that matters: evaluating
the three candidate designs on 2026-09-19 computed **Cox slope point estimates per liquidity
level, on real outcomes**, for each candidate. Those numbers were visible when 3a was chosen:

| Design | Low-liquidity slope | High-liquidity slope |
|---|---|---|
| As pre-registered | +1.136 to +1.447 | +0.411 to +0.901 |
| Within-phase (adopted) | +1.079 to +1.399 | +0.535 to +0.904 |
| Residualized | +1.162 to +1.403 | +0.413 to +0.917 |

Two things follow, and both are stated rather than argued. First, the design was chosen on
orthogonality and cell balance, which are computable without outcomes, and the contrast is
near-identical under all three candidates, so the choice cannot have been selecting whichever
design produced the largest difference. Second, the direction of the headline-2 result is
therefore **already known to the author** before the pre-registered analysis runs, and that
is a real, permanent loss of blindness which no argument undoes. What remains genuinely
untested: every bootstrap band, the phase axis, the per-stratum bin structure, the sensitivity
splits, and whether any difference survives its interval. Those are what the week 5-6
analysis reports, and the point estimates above are published alongside them so a reader can
see precisely what was known and when.

**Unchanged by this amendment:** the 150-games-per-bin floor, the single-primary-test
family-wise policy, game-level bootstrap resampling, terminal cumulative volume as the
definition wherever it exists, and section 8's honest framing that this guarantees a
measurement rather than a finding.

## 9. Risk tiers

**Omitted from the first draft. Restored here before any model fit.** PLAN.md's Phase 0 named
risk tiers as required pre-registration content and the section was simply missing; catching
it after a fit had run would have made the boundaries unfixable, since buckets are selected on
the model's own disagreement with the market.

Three tiers on the absolute edge `|p_model − p_market|`, home side, one observation per game:

| Tier | Edge band | Expectation |
|---|---|---|
| T1 | [0.02, 0.05) | Most populated; smallest and least reliable edge |
| T2 | [0.05, 0.10) | Sparse |
| T3 | >= 0.10 | May be **empty**, which is a valid published result |

Games with edge below 0.02 are not tiered: that is inside the measurement noise of the
closing price itself, which is carried forward on 41% of games (measured, week 1).

Each tier reports frequency, hit rate, calibration, and a **game-level** bootstrap interval.
The top tier is exactly where model error is largest, so its apparent edge is expected to
shrink out of sample; that expectation is stated here, before results are seen. Per-tier
results are **exploratory** under the family-wise policy in section 7, never headline.

## 10. Explicitly NOT pre-registered here

The availability / late-news hypothesis. Its data source is unproven, the historical data to
test it does not exist (`nba_api` inactives arrive post-game with no announcement timestamp),
and the forward collection cannot reach a usable n before the December deadline. It gets a
**separate addendum, committed with its own later hash**, only once a source is proven. Until
then the writeup states the hypothesis and says plainly that it is untested.

## 11. What would falsify the headline claims

- **Headline 1** is falsified as "parity" if the model's holdout Brier deficit versus the
  market exceeds the pre-stated 0.02-0.03 band. A wider gap is reported as a finding about
  the feature set, not hidden.
- **Headline 2** is falsified if the primary slope-difference test is null, which will be
  reported as "no detectable difference in calibration between strata at this n" and
  explicitly labeled underpowered rather than as evidence of market efficiency.
