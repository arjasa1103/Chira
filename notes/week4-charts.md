# Week 4 — the two Phase 2 charts, and a pre-registered bound that was wrong

Both charts are cut from the immutable snapshot `census-20260913-224d6ad985e0` (store digest
`224d6ad985e0...`, census git `1013d72`), never from the live store or the API. Outputs:
`docs/charts/chart1-coverage.png`, `docs/charts/chart2-calibration.png`, and
`docs/charts/chart-data.json` with every number behind them.

These are the **first calibration statistics ever computed on this census.** Week 3 closed
with "nothing about calibration has been established"; this is that section being filled in.

## Chart 1 — coverage by week of season

| Sport | Season | Priced / scheduled | Coverage | Worst week | Volume absent |
|---|---|---|---|---|---|
| NBA | 2024-25 | 1229 / 1230 | 99.9% | wk 1: 51/52 | 8 |
| NBA | 2025-26 | 1226 / 1230 | 99.7% | wk 14: 48/49 | 161 |
| NHL | 2024-25 | 896 / 1312 | 68.3% | **wk 1: 0/19** | 0 |
| NHL | 2025-26 | 1310 / 1312 | 99.8% | wk 1: 47/48 | 157 |

**Finding 1: NHL 2024-25's shortfall is one contiguous hole, not attrition.** Weeks 1-8 are
solid red — zero markets — and coverage begins at week 9. This was known as a monthly count
from week 3; by week of season it is unmistakably a market-launch date rather than a
collection failure, which is what makes it unfixable rather than a bug.

**Finding 2: median volume climbs steeply WITHIN every season, and this breaks an assumption
in the pre-registration.** NBA 2024-25 runs ~$50k in week 1 to ~$400k by week 18; NBA
2025-26 ~$1.0M to ~$3.2M; NHL 2024-25 ~$8k to ~$120k; NHL 2025-26 ~$250k to ~$1.0M.
PREREGISTRATION.md section 8 cuts liquidity on **within-season** volume deciles specifically
to stop "low liquidity" from meaning "2024-25". That fix works between seasons and does not
work within them: a within-season upward trend means a low volume decile is disproportionately
an early-season game, so the pre-registered 2x2 of liquidity x season phase **is not
orthogonal**. This needs resolving before the week 5-6 strata are built, not after. Logged in
TODOS.md.

**Finding 3: Gamma returned no volume field for a contiguous three-week block.** 318 priced
games have `volume IS NULL`: 161 NBA and 157 NHL, all between **2026-03-04 and 2026-03-25**,
plus 8 NBA games on 2024-11-12/13. Both sports at once across the same calendar window points
upstream, not at one sport's code path. It matters more than a chart caption because that is
13% of the 2025-26 season and it is a *calendar block*, so dropping those games from a
liquidity stratum would silently delete a specific slice of the season and re-introduce the
season-phase confound by the back door. Reported beside every median rather than dropped.

Schedule dips are visible and real (NBA 2025-26 weeks ~7 and ~17 at 21-30 games; NHL 2025-26
week ~21 at 24 games and a short final week). The likely causes are the All-Star break and the
February 2026 Olympic break; **that attribution is not verified** and nothing depends on it.

## Chart 2 — the market's own calibration at the close

Home side only, one observation per game, bins honouring the pre-registered 150-games-per-bin
floor, 2,000 game-level bootstrap replicates. **This is a reported result and has no gate
authority** (PREREGISTRATION.md section 4).

| Sport | Season | n | bins | Brier | ECE(10) | null ECE p99 | Cox slope [95% CI] | Cox intercept [95% CI] |
|---|---|---|---|---|---|---|---|---|
| NBA | 2024-25 | 1229 | 8 | 0.1992 | 0.0271 | 0.0515 | 0.990 [0.864, 1.130] | -0.0351 [-0.1584, +0.0884] |
| NBA | 2025-26 | 1226 | 8 | 0.1941 | 0.0241 | 0.0515 | 1.045 [0.914, 1.193] | +0.0074 [-0.1188, +0.1384] |
| NHL | 2024-25 | 896 | 5 | 0.2304 | 0.0349 | 0.0655 | 1.024 [0.754, 1.322] | **+0.1475 [+0.0049, +0.2881]** |
| NHL | 2025-26 | 1310 | 8 | 0.2446 | 0.0321 | 0.0553 | 0.790 [0.513, 1.082] | -0.0182 [-0.1326, +0.0975] |

Murphy decomposition (Brier = reliability - resolution + uncertainty):

| Sport | Season | Reliability | **Resolution** | Uncertainty | Home win rate | Brier gain over base rate |
|---|---|---|---|---|---|---|
| NBA | 2024-25 | 0.00069 | 0.04806 | 0.24803 | 0.5443 | 0.0488 |
| NBA | 2025-26 | 0.00059 | **0.05172** | 0.24710 | 0.5538 | 0.0530 |
| NHL | 2024-25 | 0.00145 | 0.01472 | 0.24457 | 0.5737 | 0.0142 |
| NHL | 2025-26 | 0.00132 | **0.00546** | 0.24948 | 0.5229 | 0.0049 |

**Finding 4: no sport-season shows detectable miscalibration at the close.** Every ECE sits
well inside its own per-n noise floor, and reliability is 0.0006-0.0015 against an uncertainty
of ~0.247. The curves track the diagonal. Read against the pre-registration's own framing,
this is the honest outcome it predicted: a measurement, not a finding.

**Finding 5: the real difference between the sports is resolution, not reliability.** NBA's
closing price improves on "always predict home" by 0.049-0.053 Brier; NHL 2024-25 by 0.014 and
**NHL 2025-26 by 0.005**. An NHL 2025-26 closing price is close to uninformative about who
wins. This is the substantive result of the week and it is not a calibration defect: a market
that always quotes the base rate is perfectly calibrated and useless.

**The one marginal signal, and why it is not being promoted.** NHL 2024-25's Cox intercept is
+0.1475 with a CI of [+0.0049, +0.2881], which excludes zero — home teams won more often than
the thin 2024-25 NHL market priced them to. Three reasons it stays exploratory: its null CI at
n=896 is [-0.1482, +0.1363], so it clears the floor by 0.011; it is one of sixteen statistics
in the table above, and section 7's family-wise policy reserves confirmatory status for a
single pre-registered primary test; and it is the season whose median volume is $56k. Reported,
not headlined.

**NHL 2025-26's slope of 0.790 is NOT evidence of overconfidence.** The CI [0.513, 1.082]
contains 1.0, and the null slope CI at n=1,310 on the NHL pool is [0.740, 1.267], so 0.790
sits inside the noise. Quoting it as a tilt would be exactly the over-reading the noise-floor
simulation exists to prevent.

## A pre-registered bound was wrong, and the guard test could not see it

PREREGISTRATION.md section 4 ended with an obligation: the null was built from a 128-game
**NBA-only** pool, so "the pool must be re-measured once real NHL census prices exist."
`scripts/derive_null_bands.py` discharges it. Re-simulated on the census's own closing prices
(1,500 replicates, outcomes drawn `y ~ Bernoulli(p)`, so the market is perfectly calibrated by
construction and no real outcome is touched):

| Pool | share inside [0.35, 0.65] | E[p(1-p)] |
|---|---|---|
| NBA (2,455) | 0.4053 | 0.1971 |
| NHL (2,206) | 0.8264 | 0.2375 |
| Pooled (4,661) | 0.6046 | 0.2162 |

The section-4 caveat's *predictions* were accurate — it guessed NHL at 83% and 0.2395 — but
binding them to real data changed a bound. At the pooled operative n the null slope 95% CI is
**[0.9183, 1.0908]**, which escapes the adopted `GATE_SLOPE_BAND` of [0.93, 1.08] at both
ends. Since section 4 states that bound as an equivalence test, **a perfectly calibrated
market would have failed it.** Two independent causes: the real pooled pool is more
concentrated than the NBA-only pool (mass near 0.50 is where Bernoulli variance peaks), and
the operative n is **4,661 priced games, not the 5,084 scheduled** the week-1 table assumed.

**PREREGISTRATION.md Amendment 2** widens the slope band to **[0.91, 1.10]**, rounded outward
per section 4's own rule. The other three bounds still cover their re-measured nulls and are
unchanged (ECE 0.03 vs 0.0272; max-bin-dev 0.08 vs 0.0729; intercept ±0.07 vs
[-0.0606, +0.0620]). **The amendment flips no verdict:** all four measured slope CIs fall
outside both the old and the new band, so it cannot be manufacturing a pass.

**The guard test was asserting against a pool that did not exist.**
`TestNoiseFloorIsRespected` simulated `uniform(0.1, 0.9)` at n=5,084 — less concentrated than
real moneylines and at too high an n — so its null was too narrow and it passed while the
adopted band sat inside the real null. It now asserts against the census-measured numbers
committed in `chira.constants.CENSUS_NULL_*`, plus a test of the *mechanism* (a tighter pool
must produce a wider null), so the reasoning behind the amendment fails loudly if it stops
holding. Per-n reference rows for strata live in `CENSUS_NULL_ECE_P99_BY_N`; at NHL n=896 the
null ECE p99 is 0.0655, which is 2.4x the pooled cap, so judging a stratum by the pooled
number would fail a correct pipeline outright.

## The Cox fit diverged on ordinary samples that carry no signal

Found by a chart test, not by looking for it. `cox_slope_intercept` used undamped
Newton-Raphson from a fixed `(a=0, b=1)` start — "identity calibration" as a starting
guess. On a sample whose outcome is independent of price, where the true slope is 0 and the
fit is the easiest one there is, it ran away to |slope| ~ 1e8 and then raised **"sample is
degenerate, not calibrated"**, blaming data that was nothing of the kind. Measured on six of
six seeds (n=800, verified not separable, 729 distinct prices, y mean 0.415); scipy's BFGS
puts that sample's MLE at a mundane intercept -0.4001, slope +0.0515.

The trace is a textbook undamped-Newton runaway:

| iteration | a | b | nll |
|---|---|---|---|
| start | 0 | 1 | 868.6 (MLE is 542.2) |
| 1 | -0.24 | -2.16 | 1279.3 — the first full step made it WORSE |
| 2 | +0.53 | +11.09 | 6878.9 — fitted probabilities saturate, weights pin to the 1e-9 floor |
| 3 | -51.6 | -1066 | 547,666 |
| 4+ | ~1e8 | ~1e8 | ~1e11, oscillating to the iteration cap |

**Why this was worth stopping for.** PREREGISTRATION.md section 7 makes `a + b*logit(p)` the
**null** of the single primary test, and section 4 adopts the Cox slope as a gate bound. A
market carrying little information is exactly where both get evaluated — and NHL 2025-26
already measures a Murphy resolution of 0.0055, the closest thing in this census to a
zero-signal market. The estimator was broken precisely in the regime the study depends on.

**Fix (both, since each alone suffices):** start at the intercept-only MLE (slope 0), which
is the right place to begin a search for signal; and backtrack the Newton step while it
worsens the negative log-likelihood, which makes convergence global rather than local. They
recover the exact MLE in 4 and 8 iterations respectively. Convergence is judged on the
**undamped** step, so a search that stalls by shrinking its step toward zero is reported as a
failure instead of being mistaken for a converged fit. Genuine degeneracy still raises:
constant price (singular design), perfect separation (infinite MLE), all-identical outcomes.

**Effect on every number in this document: none at 4 decimal places.** Re-cut with the fixed
estimator against the same snapshot and the same seed, the largest point-estimate change is
6.6e-11. `simulate_null` never hit the pathology — it always draws `y ~ Bernoulli(p)`, so its
outcomes carry signal by construction — which is why Amendment 2's null bands are unaffected.
One difference is worth recording rather than rounding away: **NBA 2025-26's bootstrap now
reports `cox_failures = 1` of 2,000 replicates where it previously reported 0**, moving that
CI in the 5th decimal. A resample the damped search cannot fit is now counted instead of
contributing an unconverged fit, which is what the failure counter exists for.

**The test that would have caught it** is now `tests/test_cox_fit.py`: six zero-signal seeds
that must fit a near-zero slope, the scipy MLE pinned to four decimals, a guard that the
previously-correct value 0.925262 has not moved, and the degeneracy cases that must still
raise.

## The synthetic scorer (T10 / E8)

`tests/test_scorer_synthetic.py` validates the instrument before it judges the market. A
market is built as `expit(k * logit(p_true))` with outcomes drawn from `p_true`, so its true
calibration is known by construction: `k=1` is perfect, `k>1` is overconfident and must return
a Cox slope near `1/k`. Covered: perfect market scores inside the gate across five seeds
(specificity — a scorer that flags everything passes every other test); a 25% overconfident
market returns slope < 1 and a 20% underconfident one returns slope > 1, with the two ordered;
a shifted market moves the intercept the correct way; an orientation flip returns a **negative**
slope; and a coin-flip market is not credited with resolution. Deliberately not asserted
against the `GATE_*` constants — those govern the census pool, and borrowing them for a
uniform pool would measure the mismatch between two pools rather than the scorer.

## Which sport is primary

**NBA.** Coverage 99.9%/99.7% against 68.3%/99.8%, where the NHL shortfall is an unfixable
eight-week hole that leaves it with ~1.5 usable seasons to NBA's 2. Resolution 0.0481/0.0517
against 0.0147/0.0055. And NBA closes span 0.045-0.980 with 40.5% inside [0.35, 0.65] against
NHL's 0.200-0.825 and 82.6% — NHL has almost no favourites or longshots, which is both the tail
where the literature puts the bias headline 2 hunts and what a calibration curve needs in order
to have any shape. NHL is still retained, because PLAN.md makes it load-bearing for headline
2's per-stratum n; but its near-zero resolution is a new risk to that role and should be
re-checked before the strata are built.

## What was NOT established

- **Nothing stratified.** These curves are pooled within sport-season. Headline 2's 2x2 is
  week 5-6 work, and finding 2 above says its design needs revisiting first.
- **Nothing about the model.** No feature, no fit, no holdout. The 2025-26 season remains
  sealed; note that chart 2 reports statistics on it, which is intended — section 6 seals it
  against MODEL fitting, and the market's own calibration is a headline-2 descriptive.
- **The other three looks are uncomputed.** Only the close is charted. T-1h/T-6h/T-24h are
  loaded and coverage-checked (`look_coverage`), but T-24h is missing on 133 games, so the four
  looks do not share a denominator and a naive four-curve comparison would be wrong.
- **The volume-null block is uninvestigated.** 318 games, cause assumed upstream from the fact
  that both sports break in the same window. Not confirmed against Gamma.
- **The within-season volume trend is measured, not modelled.** Finding 2 says the 2x2 is
  confounded; it does not say by how much.
