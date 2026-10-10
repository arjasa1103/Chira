# Week 9 — the holdout, opened once

PREREGISTRATION Amendment 5e: *"2025-26 labels reach the model only through a single
function that refuses a dirty tree, refuses a second call, and commits a marker with the
frozen commit hash and time."* That function ran on **2026-10-06 at 16:07:07Z**, against
commit **`dc384cc5f4f6`**, releasing **2,542 labels** with SHA-256
`e367f5812c7637…`. The marker is `HOLDOUT_OPENED.json`, committed and pushed before a
single label came back.

That moment cannot be repeated. Everything below is what it bought.

Numbers: `data/holdout/holdout.json`. Figure: `docs/charts/chart5-holdout-reliability.png`,
drawn by the same `charts.chart_reliability` that cut chart 4 on dev. The dev counterparts
every table here mirrors are in [notes/week8-model.md](week8-model.md) and
`data/rehearsal/dress-rehearsal.json`.

**This pass is deliberately absent from `scripts/reproduce.py`.** That script ends at the
dress rehearsal. A one-shot irreversible act does not belong in a pipeline that invites
re-running, and `open_holdout` would refuse anyway.

## How the pass actually went — two attempts, one look

The first invocation **opened the seal and then crashed before printing a number.**
`run_holdout.py` called `scoring.risk_tiers(p, y)` against a signature that a review
commit (`041cc42`) had already changed to `risk_tiers(p_model, p_market, y)`. The seal
broke at 16:07:07Z; the script died seconds later on a `TypeError`.

**The labels were out and nothing had been computed from them.** The fix was a
recomputation path (`06712ed`, `6aa7ea2`) whose preconditions are deliberately different
from the opening's:

| | first look | recomputation |
|---|---|---|
| clean tree | required | not required |
| HEAD pushed | required | not required |
| no marker here or on the remote | required | **marker required** |
| labels hash to the marker's record | — | **required** |

The distinction is real rather than a relaxation to make a script run: a reader checks the
marker's commit, time and label hash, and none of the three move when the analysis is
re-derived from labels already released. What the clean-tree and pushed-HEAD checks protect
is the claim *"the model was frozen and public before anything was seen"*, and that claim is
pinned to `dc384cc5f4f6` whatever happens afterwards. The recomputation verified the digest
and refuses if the store has shifted.

**This is a process deviation and is recorded as one.** A dress rehearsal exists so that
opening the holdout only fills in numbers; it rehearsed the statistics faithfully and did
not rehearse the runner against its own imports. The rehearsal ran `risk_tiers` through
`run_dress_rehearsal.py`, which had been updated in `041cc42`; `run_holdout.py` was written
after it and never executed. A dry run with `--open-the-seal` stubbed out would have caught
it, and there was no such mode.

## The headline, stated before the tables

**Headline 1 passes as parity, in both sports, by a wide margin.** The pre-registered
falsification condition (section 11) was a Brier deficit against the market **exceeding the
0.02-0.03 band**. Measured:

| | model | market | deficit | band |
|---|---|---|---|---|
| NBA | 0.20592 | 0.19413 | **+0.01179** | 0.02-0.03 |
| NHL | 0.24971 | 0.24459 | **+0.00512** | 0.02-0.03 |

Both deficits are *under* the band's lower edge. On the pre-registered criterion, a
transparent schedule-and-rating model reaches parity with Polymarket's closing price.

**The two sports get there for opposite reasons, and only one of them is a result.**

- **NBA parity is real.** The market resolves 0.05201 of the 0.24710 outcome variance; the
  model resolves 0.04118, which is **79% of the market's resolution**, with reliability
  0.00135 against the market's 0.00095. Two forecasters that both say something, close
  together.
- **NHL parity is vacuity.** Market resolution is **0.00571** and the model's **0.00362**,
  roughly a ninth of the NBA's. The NHL model's Brier (0.24971) is **worse than always
  forecasting the base rate** (0.24951) by 0.00020. The market beats the base rate by
  0.00492. The deficit is small because there is almost nothing to be better at.

Reporting "parity in both sports" without that second bullet would be the most misleading
true sentence available in this project.

## 1. Scores on 2025-26

NBA n=1,230 games (1,226 priced); NHL n=1,312 (1,310 priced). 1,226 + 1,310 + the 6
unpriced = 2,542, the marker's label count.

### NBA
| forecaster | n | Brier | log loss | ECE | reliability | resolution |
|---|---|---|---|---|---|---|
| market (close) | 1,226 | **0.19413** | 0.56879 | 0.02407 | 0.00095 | 0.05201 |
| Elo (frozen) | 1,230 | 0.20421 | 0.59517 | 0.02843 | 0.00105 | 0.04296 |
| model | 1,230 | 0.20592 | 0.59827 | 0.03001 | 0.00135 | 0.04118 |
| base rate | 1,230 | 0.24703 | 0.68720 | 0.04228 | 0.00268 | 0.00268 |

Uncertainty 0.24703. Model skill over the base rate: **+0.04111** Brier.

### NHL
| forecaster | n | Brier | log loss | ECE | reliability | resolution |
|---|---|---|---|---|---|---|
| market (close) | 1,310 | **0.24459** | 0.68207 | 0.03209 | 0.00136 | 0.00571 |
| base rate | 1,312 | 0.24951 | 0.69217 | 0.01826 | 0.00052 | 0.00052 |
| model | 1,312 | 0.24971 | 0.69302 | 0.05641 | 0.00406 | 0.00362 |
| Elo (frozen) | 1,312 | 0.25065 | 0.69488 | 0.06264 | 0.00544 | 0.00438 |

Uncertainty 0.24951. Model skill over the base rate: **−0.00020** Brier. The ordering is
the finding: in the NHL, *the base rate outscores both the model and the rating.*

## 2. The dress rehearsal's headline partly inverts

The rehearsal's framing, decided **2026-10-04** and pushed in `369a9d5` **before** the
seal (docs/checklist.md), was: *out of sample the model does not beat the Elo it is built
on.* On dev that held in both sports.

| model − Elo, Brier | dev (rolling origin) | holdout |
|---|---|---|
| NBA | +0.00282 | **+0.00171** |
| NHL | +0.00269 | **−0.00094** |

The NBA gap survives and halves. **The NHL gap flips sign**: on the holdout the model beats
its own rating, on Brier (−0.00094), log loss (−0.00186) and ECE (−0.00623). Both margins
are far inside anything this n can separate, so the honest statement is that **model and
rating are indistinguishable out of sample, in both sports** — not that the rehearsal was
wrong and not that the model won.

The framing was written down before the seal and **stands unamended**. It was stated as a
claim about dev, it is weakened rather than contradicted, and amending it now, with the
holdout in view, is exactly the move section 6 exists to prevent.

## 3. What the holdout settles that dev could not: the Elo overlap

TODOS carried a P2 that dev could not close. Amendment 5b disclosed that the Elo's three
constants (K, H, c) were tuned by log loss over **all of 2024-25**, the same season the
rolling origin scores — so on dev the Elo column was in-sample for three parameters while
the model column was not, biasing the comparison toward the rating by an unmeasured amount.
The fix on dev is to refit K/H/c inside each fold. **It was never done.**

On the holdout the bias is gone by construction: the constants were frozen and pushed on
2026-10-01 (`d66671c`), before any 2025-26 rating existed, and were never tuned on 2025-26
by anything. Both columns are honestly out of sample. That is what section 3's answer rests
on, and it is why the unmeasured dev bias no longer gates headline 1.

**The P2 is not thereby closed as work** — the dev number would still tell you how much of
the rehearsal's +0.00282 was artefact. It is closed as a *blocker*.

## 4. Every team-season in the holdout is unseen, and that changes what was measured

`model.predict` integrates team-season random effects out of the fitted hyperprior for
team-seasons with no dev estimate. On this pass that is **30 of 30 NBA team-seasons and 32
of 32 NHL** — all of them, necessarily, since a 2025-26 team-season cannot appear in a
2024-25 fit.

So on the holdout Model B is: the frozen Elo covariate, the schedule terms (rest, b2b,
travel, time-zone), a pooled home advantage, and team effects marginalised to the
hyperprior mean. **The component that most distinguishes the model from the rating on dev
is switched off by construction here.** That is a structural reason to expect model and Elo
to converge out of sample, and section 2 is what that looks like: +0.00171 and −0.00094.

This was designed in (Amendment 5c's prediction path, `447933c`) and disclosed before the
pass. It is stated here because "the model matches its rating" reads very differently once
you know the model was predicting with its team effects integrated out.

## 5. Calibration against the per-n null

Section 4's bounds are **"evaluated on the FULL census (n ≈ 5,084), never on the holdout"**,
and per-stratum work must use the matching row of `CENSUS_NULL_ECE_P99_BY_N` rather than the
pooled 0.03 cap. The relevant rows are `("nba", 1226) = 0.0515` and
`("nhl", 1310) = 0.0553`.

| | ECE | null p99 at this n | |
|---|---|---|---|
| NBA market | 0.02407 | 0.0515 | inside |
| NBA Elo | 0.02843 | 0.0515 | inside |
| NBA model | 0.03001 | 0.0515 | inside |
| NHL market | 0.03209 | 0.0553 | inside |
| NHL model | **0.05641** | 0.0553 | **over, by 0.0011** |
| NHL Elo | **0.06264** | 0.0553 | **over** |

Read strictly: the only calibration failures on the holdout are the **NHL model and the NHL
rating**, the model's by a hair. Nothing in the NBA is distinguishable from perfect
calibration at this n. The NHL market is fine.

This is a reference comparison, not a gate — the gate lives on the census and was never
pointed at the holdout.

## 6. Reliability buckets (exploratory, not section 9)

Five fixed model-probability bins. Under section 7's family-wise policy these are
**exploratory and never headline**. CIs are game-level bootstraps, 2,000 reps.

### NBA — all five contain their own forecast
| bin | n | mean forecast | observed | 95% CI |
|---|---|---|---|---|
| [0.00, 0.35) | 224 | 0.2554 | 0.2411 | [0.1875, 0.2946] |
| [0.35, 0.45) | 169 | 0.4006 | 0.3728 | [0.3018, 0.4438] |
| [0.45, 0.55) | 213 | 0.4991 | 0.5540 | [0.4836, 0.6197] |
| [0.55, 0.65) | 223 | 0.6001 | 0.6099 | [0.5426, 0.6728] |
| [0.65, 1.00) | 401 | 0.7612 | 0.7756 | [0.7332, 0.8155] |

### NHL — two adjacent bins exclude their forecast, in the same direction
| bin | n | mean forecast | observed | 95% CI | |
|---|---|---|---|---|---|
| [0.00, 0.35) | 25 | 0.3052 | 0.4000 | [0.2000, 0.6000] | n too small to say anything |
| [0.35, 0.45) | 127 | 0.4150 | 0.4252 | [0.3465, 0.5118] | contains |
| [0.45, 0.55) | 436 | 0.5065 | 0.4931 | [0.4450, 0.5413] | contains |
| [0.55, 0.65) | 494 | 0.5963 | 0.5324 | **[0.4919, 0.5769]** | **excludes** |
| [0.65, 1.00) | 230 | 0.6973 | 0.6217 | **[0.5609, 0.6826]** | **excludes** |

**The dev miscalibration did not replicate, and a different one appeared.** TODOS' P2 was
the NHL **[0.35, 0.45)** bucket, which on dev held 185 games at mean forecast 0.4069 against
an actual 0.5243, CI [0.4595, 0.5892] excluding the forecast. That decision — keep it as an
exploratory reliability row, state it, do not recalibrate — was taken 2026-10-04 and pushed
before the seal. On the holdout that bucket is **fine**: 0.4150 forecast, 0.4252 observed,
CI straddling.

What is wrong instead is the NHL **favourite side**: both bins above 0.55 are overconfident,
by 0.064 and 0.076, with 724 of 1,312 games between them. The model says 0.60-0.70 and the
teams win 0.53-0.62. Same direction, adjacent bins, two thirds of the schedule — not a
single-bucket fluke.

**The P2 decision was right for the wrong bucket.** Had the dev bucket been recalibrated,
the holdout would have shown the fix landing on the one region that did not need it, with
the real defect untouched and the pass spent. That is the argument for the seal, made by
accident.

## 7. Risk tiers (section 9)

Edge bands on `|p_model − p_market|`, home side, one row per game, on priced games only.
"Hit" is the outcome going the way the **model** leaned relative to the market: home won
where the model priced home above the market, away won where below. Section 9 pre-stated
that T3's apparent edge is expected to **shrink** out of sample.

### NBA — 1,226 priced, 203 below the 0.02 floor
| tier | band | n | share | mean edge | model-side hit | 95% CI | |
|---|---|---|---|---|---|---|---|
| T1 | [0.02, 0.05) | 311 | 25.4% | 0.0347 | 0.4019 | [0.3473, 0.4598] | below 0.5 |
| T2 | [0.05, 0.10) | 360 | 29.4% | 0.0743 | 0.3139 | [0.2694, 0.3611] | below 0.5 |
| T3 | ≥ 0.10 | 352 | 28.7% | 0.1563 | 0.3239 | [0.2756, 0.3778] | below 0.5 |

**All three NBA tiers' intervals lie entirely below 0.5.** Where the NBA model disagrees
with the market, the market side wins 60-69% of the time, and the effect is strongest
exactly where the model is most confident it disagrees. On dev only T3 cleared 0.5 downward
(0.3542 [0.3084, 0.4000]); T1 and T2 straddled it at 0.4555 and 0.4536. The expectation
section 9 pre-stated — top-tier edge shrinks — understated it: **all** the apparent edge
inverted.

In-tier calibration says the same thing more quietly. T1: home won 0.5852 while the model
said 0.5697 and the market 0.5746. The market is closer in every tier.

### NHL — 1,310 priced, 333 below the floor
| tier | band | n | share | mean edge | model-side hit | 95% CI | |
|---|---|---|---|---|---|---|---|
| T1 | [0.02, 0.05) | 404 | 30.8% | 0.0345 | 0.4455 | [0.3960, 0.4950] | below 0.5 |
| T2 | [0.05, 0.10) | 427 | 32.6% | 0.0717 | 0.5222 | [0.4707, 0.5691] | straddles |
| T3 | ≥ 0.10 | 146 | 11.1% | 0.1296 | 0.4247 | [0.3493, 0.5068] | straddles |

The NHL is a coin flip with one tier under it. Nothing here is a disagreement worth acting
on in either direction, which is the correct reading of a sport whose market resolves
0.00571.

**Across both sports, 536 of 2,536 priced games (21%) have no tier at all** — edge under
0.02, inside the measurement noise of the closing price, which is carried forward on 41% of
games (week 1). Those games are excluded by pre-registration, not by selection.

## 8. The nested test (section 7)

Clark-West with the MSPE adjustment, stationary bootstrap over calendar dates, 2,000 reps.
Model B nests the null literally. Two nulls: **identity** (the raw closing price) and
**recalibrated** (that price through a logistic fitted on dev). Two closing constructions:
`close` and `t1h`. **NBA is the primary sample; NHL is the contrast case** (section 3b), and
the family-wise policy admits one primary test.

| sport | horizon | null | CW | bootstrap p | n (dates) | dev CW (p) |
|---|---|---|---|---|---|---|
| **NBA** | close | identity | −1.0607 | 0.8695 | 1,226 (164) | −0.3341 (0.6165) |
| **NBA** | close | recalibrated | −0.9673 | 0.8390 | 1,226 (164) | −0.0717 (0.5105) |
| NBA | t1h | identity | −1.0024 | 0.8480 | 1,226 (164) | −0.3681 (0.6370) |
| NBA | t1h | recalibrated | −0.9284 | 0.8350 | 1,226 (164) | −0.1129 (0.5235) |
| NHL | close | identity | +0.6714 | 0.2180 | 1,310 (167) | −0.0551 (0.5370) |
| NHL | close | recalibrated | **+2.3552** | **0.0030** | 1,310 (167) | −0.0273 (0.5265) |
| NHL | t1h | identity | +0.7140 | 0.2100 | 1,310 (167) | −0.0566 (0.5395) |
| NHL | t1h | recalibrated | **+2.3594** | **0.0065** | 1,310 (167) | +0.0049 (0.5075) |

**The primary test is null, and more decisively than on dev.** NBA close against identity:
CW −1.06, p 0.87. The model's covariates add **nothing** to the NBA closing price, under
either null, under either construction. Negative CW with the MSPE adjustment applied means
the nesting model is worse than the null even after being credited for its extra parameters.
Consistent with section 7's direction and with sections 1 and 7.

**The NHL contrast splits on the null, and the split points at the recalibration rather
than at the covariates.** Against identity, p 0.218 — nothing. Against recalibrated,
p 0.003. B's mean adjusted advantage is **0.00080 over the raw closing price and 0.00182
over the recalibrated one**: the same B, the same games, the same covariates, and more than
twice the margin once the baseline is passed through a dev-fitted logistic. What moved is
the null, not the model. Since B nests that recalibration, part of what it is being credited
for is undoing it. Claiming "the model adds information to the NHL market" from the
significant row, while the row against the actual market price is null, would be reading a
weakened baseline as a discovery.

**It is still an inversion from dev and must not be smoothed over.** Every dev CW sat within
0.06 of zero. Two things changed at once: the dev NHL test ran on n=717 across 4 folds (Nov
and Dec skipped for want of priced games) against 1,310 games and 167 dates here, so dev was
underpowered; and the dev recalibration was fitted and scored inside the same season, where
its transfer cost cannot show up. Nothing distinguishes those two causes on the evidence
available, and the seal is spent, so this stays an open question rather than a conclusion.

## 9. Against the pre-registered falsification conditions

- **Headline 1 — passes as parity.** Deficits +0.01179 (NBA) and +0.00512 (NHL), both below
  the 0.02-0.03 band that would have falsified it. Decomposed in section 1, as PLAN Phase 5
  required. The NHL pass is qualified in the headline above and must stay qualified wherever
  it is quoted.
- **Headline 2 — untouched by this pass.** It is a descriptive finding on terminal volume
  from week 5, on census prices, and no holdout label enters it.
- **T5 (MCMC diagnostics as hard failure)** — the two holdout fits passed; any divergence or
  R-hat > 1.01 raises, and a single-chain run is refused. **The values were printed and not
  persisted** (see section 10).
- **T17 (the measured ceiling)** — dev only, by design. The GBM was worse in both sports
  (NBA 0.23055 vs 0.21250; NHL 0.24891 vs 0.23954), so the cost of interpretability is
  negative. Never re-run on the holdout and should not be.
- **Deviation 1 (the 2026-10-01 scoring leak)** — unchanged, and its rule held: **no model
  change was made in response to any dev or holdout behaviour.** The structural fix,
  `holdout.assert_scorable`, is what made it impossible to repeat.

## 10. Gaps this pass leaves, recorded rather than hidden

1. **`chart_reliability`'s statistics were computed and thrown away.** It returns Cox slope,
   intercept, per-bin curve and bootstrap band per panel; `run_holdout.py` calls it for the
   PNG and discards the return. The figure carries the slopes visually and the JSON does not
   carry them at all. Re-deriving them from released labels is a legitimate recomputation
   (section "how the pass went"), and `CENSUS_NULL_SLOPE_CI_BY_N` holds the per-n nulls to
   read them against. **The runner should persist what it draws.**
2. **The holdout fits' diagnostics are not in the JSON either.** Divergences and R-hat went
   to stdout. The gate is enforced in code — an unconverged fit raises — so the pass could
   not have proceeded without them, but "T5 passed" is currently an assertion backed by a
   raise rather than a recorded number.
3. **The Elo overlap is still unmeasured on dev** (section 3). No longer a blocker; still the
   number that would tell you how much of the rehearsal's +0.00282 was artefact.
4. **The dress rehearsal did not rehearse the runner.** Section "how the pass went". A
   `--dry-run-the-analysis` mode that exercises every call on dev rows would have cost
   nothing and saved the crash.

## 11. What this pass does not say

It does not say the model is good. It says a transparent model built from a frozen rating
and a schedule reaches the pre-registered parity bar against a prediction market, and that
where it disagrees with that market in the NBA it is **wrong more often than right, in every
tier** (section 7).

It does not say the NHL is predictable. Both forecasters sit within 0.005 Brier of a
constant, and the model sits on the wrong side of it.

It does not license a second look. `open_holdout` refuses a second call, the marker records
what was seen and when, and every number above is final.
