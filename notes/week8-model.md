# Week 8 — the model, and the dress rehearsal on dev

PREREGISTRATION section 6: *"A full dress rehearsal on dev must first produce every
table and figure that will appear in the writeup, so opening the holdout only fills in
numbers."* This is that rehearsal. **Every number here is 2024-25.** The sealed 2025-26
season was not read, and `holdout.assert_scorable` would refuse it if a future edit
tried.

Reproduce with `uv run python scripts/run_dress_rehearsal.py`; the JSON behind every
table is `data/rehearsal/dress-rehearsal.json`.

## The headline, stated before the tables

**Out of sample, the model does not beat the frozen Elo rating it is built on.** NBA
Brier 0.21250 against 0.20968; NHL 0.23954 against 0.23685. In sample it did win
(0.20427 against 0.21044 on the NBA), which is what overfitting looks like from the
inside.

**Both beat the base rate comfortably**, and the gap between model and rating is small
next to that: the NBA model is 0.035 Brier better than "always the home rate" and 0.003
worse than the rating alone.

**One caveat makes this less than a verdict, and it was disclosed in advance.**
Amendment 5b's disclosed overlap: the Elo's three constants were tuned by log loss over
all of 2024-25, which is the same season the rolling origin runs on. So the Elo column is
in-sample with respect to K, H and c while the model column is honestly out of sample.
The comparison is biased toward the rating by an amount this project has not measured.
Measuring it means refitting K/H/c inside each fold, which is dev-only work and therefore
legitimate; it has not been done, and **no model change has been made in response to any
of this** (PREREGISTRATION Deviation 1's rule).

## 1. The rolling origin (Amendment 5c)

Six monthly origins, October training-only. Each fold refits the standardisation and the
missing-value medians on that fold's training games alone -- dev-wide statistics would
carry April into November.

### NBA
| origin | train | test | divergences | max R-hat |
|---|---|---|---|---|
| 2024-11-01 | 67 | 222 | 0 | 1.0004 |
| 2024-12-01 | 289 | 191 | 0 | 1.0011 |
| 2025-01-01 | 480 | 224 | 0 | 1.0011 |
| 2025-02-01 | 704 | 173 | 0 | 1.0011 |
| 2025-03-01 | 877 | 245 | 0 | 1.0007 |
| 2025-04-01 | 1,122 | 108 | 0 | 1.0042 |

### NHL
| origin | train | test | divergences | max R-hat |
|---|---|---|---|---|
| 2024-11-01 | 164 | 212 | 0 | 1.0008 |
| 2024-12-01 | 376 | 215 | 0 | 1.0004 |
| 2025-01-01 | 591 | 229 | 0 | 1.0018 |
| 2025-02-01 | 820 | 123 | 0 | 1.0011 |
| 2025-03-01 | 943 | 235 | 0 | 1.0008 |
| 2025-04-01 | 1,178 | 134 | 0 | 1.0018 |

Every one of the twelve fits converged: no divergences anywhere, worst R-hat 1.0042
against the pre-registered 1.01 ceiling. The ceiling is a hard failure (T5), and the
sample count was raised from 1000 to 1500 draws precisely because 1000 left 0.0003 of
margin.

## 2. Out of sample, pooled over folds

### NBA (n=1,163)
| forecast | Brier | log loss | ECE |
|---|---|---|---|
| model | 0.21250 | 0.61105 | 0.03008 |
| Elo alone | 0.20968 | 0.60611 | 0.01752 |
| GBM ceiling | 0.23055 | 0.65766 | 0.05925 |
| base rate | 0.24788 | 0.68891 | 0.03400 |

### NHL (n=1,148)
| forecast | Brier | log loss | ECE |
|---|---|---|---|
| model | 0.23954 | 0.67306 | 0.05403 |
| Elo alone | 0.23685 | 0.66621 | 0.03429 |
| GBM ceiling | 0.24891 | 0.69236 | 0.08053 |
| base rate | 0.24550 | 0.68412 | 0.03633 |

**The model's calibration is worse than the rating's**, not just its sharpness: NBA ECE
0.0301 against 0.0175, NHL 0.0540 against 0.0343. Fitting a model on top of a
well-calibrated rating made it less calibrated, which is a cleaner statement of the same
overfitting.

## 3. The GBM ceiling (T17): interpretability is free here

T17 exists because *"the interpretability veto is an assertion, not a measurement"*.
Same folds, same covariates, scikit-learn's `HistGradientBoostingClassifier` at stated
defaults with early stopping taken from the training fold only.

| | model Brier | GBM Brier | cost of interpretability |
|---|---|---|---|
| NBA | 0.21250 | 0.23055 | **−0.01805** |
| NHL | 0.23954 | 0.24891 | **−0.00937** |

**The cost is negative in both sports: the black box is worse.** So the answer T17 asked
for is that interpretability costs nothing measurable here, and the honest reading is
narrow -- it says this feature set has little non-linear structure for a booster to
find at ~1,000 training rows and five covariates, not that boosting is a bad method. A
stronger ceiling was used deliberately rather than a hand-rolled one, because an
under-powered ceiling would have manufactured this result.

The GBM is reported and **not shipped**: nothing downstream imports a prediction from it.

## 4. Hyperprior sensitivity (section 5)

*"On hierarchical variance parameters the prior can be the result."* Each variance prior
was scaled by ½ and 2 and the model refitted.

### NBA
| parameter | prior scale | posterior mean (sd) | b_rating |
|---|---|---|---|
| `tau_team` ×0.5 | 0.250 | 0.1026 (0.0752) | +0.8989 |
| `tau_team` ×1 | 0.500 | 0.1186 (0.0871) | +0.8879 |
| `tau_team` ×2 | 1.000 | 0.1214 (0.0877) | +0.8868 |
| `tau_home` ×0.5 | 0.125 | 0.0981 (0.0688) | +0.8939 |
| `tau_home` ×1 | 0.250 | 0.1387 (0.0908) | +0.8923 |
| `tau_home` ×2 | 0.500 | 0.1554 (0.0989) | +0.8926 |

### NHL
| parameter | prior scale | posterior mean (sd) | b_rating |
|---|---|---|---|
| `tau_team` ×0.5 | 0.250 | 0.0712 (0.0527) | +0.3923 |
| `tau_team` ×1 | 0.500 | 0.0753 (0.0566) | +0.3920 |
| `tau_team` ×2 | 1.000 | 0.0742 (0.0574) | +0.3911 |
| `tau_home` ×0.5 | 0.125 | 0.0876 (0.0606) | +0.3924 |
| `tau_home` ×1 | 0.250 | 0.1155 (0.0786) | +0.3910 |
| `tau_home` ×2 | 0.500 | 0.1232 (0.0824) | +0.3898 |

**No variance parameter tracks its prior.** The sharpest case is NBA `tau_home`, whose
posterior mean moves 0.0981 → 0.1554 (a factor of 1.58) while its prior scale moves by a
factor of 4 -- about 20% of the prior's change, under the 25% threshold but not nothing,
and worth stating rather than rounding to "clean". `tau_team` barely moves at all
(0.1026 → 0.1214 against the same 4× prior change). `b_rating` is stable to the fourth
decimal throughout, so the rating coefficient -- the thing the model is actually for --
does not depend on these priors.

## 5. Risk tiers

Pre-registered buckets, model predictions, out of sample, with game-level bootstrap
intervals.

### NBA
| bucket | n | share | mean p | actual | 95% CI |
|---|---|---|---|---|---|
| [0.00, 0.35) | 241 | 20.7% | 0.2461 | 0.2905 | [0.2324, 0.3485] |
| [0.35, 0.45) | 146 | 12.6% | 0.3987 | 0.4315 | [0.3560, 0.5137] |
| [0.45, 0.55) | 178 | 15.3% | 0.5024 | 0.5056 | [0.4326, 0.5787] |
| [0.55, 0.65) | 194 | 16.7% | 0.5998 | 0.5361 | [0.4639, 0.6031] |
| [0.65, 1.00) | 404 | 34.7% | 0.7727 | 0.7624 | [0.7228, 0.8020] |

### NHL
| bucket | n | share | mean p | actual | 95% CI |
|---|---|---|---|---|---|
| [0.00, 0.35) | 79 | 6.9% | 0.2786 | 0.3291 | [0.2278, 0.4304] |
| [0.35, 0.45) | 185 | 16.1% | 0.4069 | 0.5243 | [0.4486, 0.5946] |
| [0.45, 0.55) | 330 | 28.7% | 0.5034 | 0.5182 | [0.4636, 0.5727] |
| [0.55, 0.65) | 301 | 26.2% | 0.5976 | 0.6080 | [0.5515, 0.6645] |
| [0.65, 1.00) | 253 | 22.0% | 0.7163 | 0.6877 | [0.6285, 0.7391] |

**The NBA top tier holds up**: 34.7% of games at mean p 0.773 against an actual 0.762.
The expected top-tier shrinkage was stated up front and it is mild.

**One NHL bucket is genuinely broken.** [0.35, 0.45) holds 185 games at mean p 0.4069
against an actual **0.5243**, and the interval [0.4595, 0.5892] **excludes** the
forecast. The model calls those games a 41% home win and they come in at 52%. That is a
real miscalibration in the NHL's most common region, and it is where the ECE above comes
from.

## 6. The nested test, rehearsed (section 7)

Model A is the market price, Model B is the market price plus features, with B literally
nesting `a + b·logit(p)` so Clark-West applies. Both nulls, both closing-price
constructions, stationary bootstrap over calendar dates.

### NBA
| closing price | null | CW | p (normal) | p (date bootstrap) | n |
|---|---|---|---|---|---|
| close | identity | +1.533 | 0.0626 | 0.0485 | 1,163 |
| close | recalibrated | +1.515 | 0.0649 | 0.0380 | 1,163 |
| t1h | identity | +1.577 | 0.0573 | 0.0475 | 1,162 |
| t1h | recalibrated | +1.545 | 0.0611 | 0.0410 | 1,162 |

### NHL
| closing price | null | CW | p (normal) | p (date bootstrap) | n |
|---|---|---|---|---|---|
| close | identity | +2.650 | 0.0040 | 0.0015 | 896 |
| close | recalibrated | +1.495 | 0.0675 | 0.0815 | 896 |
| t1h | identity | +2.597 | 0.0047 | 0.0025 | 896 |
| t1h | recalibrated | +1.432 | 0.0761 | 0.1075 | 896 |

**The two nulls say different things in the NHL, which is exactly why there are two.**
Against the raw price, B is strong (CW +2.65, p 0.004 normal / 0.0015 bootstrap).
Against a *recalibrated* price it is not significant (CW +1.50, p 0.068 / 0.082). Section
7 pre-stated the reading: *"Winning only against the identity null is a recalibration
finding about a public tilt, not evidence of private information."* So almost all of B's
apparent advantage over the NHL market is fixing the market's calibration tilt -- which
is headline 2's result arriving from a different direction.

The NBA is weaker and more uniform: CW +1.5 against both nulls, p around 0.06 analytic
and 0.04 bootstrapped, i.e. nothing to lean on.

**The analytic and bootstrap p-values disagree** (NBA: 0.0649 against 0.0380 on the
recalibration null), and section 7 asked for both precisely so that disagreement is
visible. The bootstrap is the one to quote: it carries the date clustering.

**This is a rehearsal, not the test.** The pre-registered nested test is one pass over
the sealed holdout, after the model is frozen by commit. These dev numbers exist so that
pass has nothing left to decide.

## What the holdout pass still has to fill

- Every table above, recomputed once on 2025-26 through `holdout.open_holdout`.
- Reliability diagrams for the model and the market side by side (the figure is not cut
  yet; the binned curve machinery is `calibration.binned_curve`, already used by chart 2).
- The headline-1 verdict against its pre-stated band: a 0.02-0.03 Brier deficit against
  the market, decomposed and explained.

## Open, and worth deciding before week 9

1. **The Elo overlap is unquantified.** Refitting K/H/c inside each rolling-origin fold
   would make the model-versus-rating comparison fair. Dev-only, legitimate, not done.
2. **The NHL [0.35, 0.45) bucket.** A known miscalibration in the busiest region of the
   NHL's distribution, going into a holdout pass that cannot be repeated.
3. **Headline 1's framing.** On current evidence it is "a schedule-and-rating model
   matches its own rating and both trail the market", not "the model beats the line".
