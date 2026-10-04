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

**When these choices were made.** Section 5 makes the analysis mandatory but names no
alternative priors and no threshold. The ×½ / ×2 multipliers and the 25% "prior-driven"
cut (`model.prior_driven`) were chosen in the same commit as these results (`a925fad`),
not written down beforehand. Everything here is dev, so the seal is not involved, but the
25% figure is a reading aid set alongside the numbers, not a pre-registered threshold.

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
factor of 4 -- about 20% of the prior's change, under the 25% reading aid but not nothing,
and worth stating rather than rounding to "clean". `tau_team` barely moves at all
(0.1026 → 0.1214 against the same 4× prior change). `b_rating` is stable to the fourth
decimal throughout, so the rating coefficient -- the thing the model is actually for --
does not depend on these priors.

## 5. Risk tiers (section 9), and reliability by probability bucket

**Corrected on review, 2026-10-04.** The first version of this section printed five
buckets on the model's own probability and called them the pre-registered risk tiers.
Section 9 defines something else: three tiers on the edge `|p_model − p_market|` at the
close, games under 0.02 left untiered, each tier's hit rate being how often the outcome
went the way the model leaned relative to the market. Those are now computed below; the
probability buckets survive as an exploratory reliability table.

### Section 9's tiers, out of sample

**NBA** (n=1,163 priced; 187 under the 0.02 floor, not tiered)

| tier | edge | n | share | mean edge | hit rate | 95% CI | home won / model / market |
|---|---|---|---|---|---|---|---|
| T1 | [0.02, 0.05) | 281 | 24.2% | 0.0342 | 0.4555 | [0.4021, 0.5125] | 0.5587 / 0.5752 / 0.5769 |
| T2 | [0.05, 0.10) | 280 | 24.1% | 0.0734 | 0.4536 | [0.3964, 0.5107] | 0.5571 / 0.5537 / 0.5616 |
| T3 | >= 0.10 | 415 | 35.7% | 0.1785 | **0.3542** | [0.3084, 0.4000] | 0.5108 / 0.5161 / 0.5261 |

**NHL** (n=896 priced; 203 under the floor)

| tier | edge | n | share | mean edge | hit rate | 95% CI | home won / model / market |
|---|---|---|---|---|---|---|---|
| T1 | [0.02, 0.05) | 260 | 29.0% | 0.0348 | 0.4308 | [0.3692, 0.4962] | 0.5769 / 0.5452 / 0.5479 |
| T2 | [0.05, 0.10) | 276 | 30.8% | 0.0715 | 0.4710 | [0.4130, 0.5326] | 0.5725 / 0.5395 / 0.5359 |
| T3 | >= 0.10 | 157 | 17.5% | 0.1424 | 0.4713 | [0.3949, 0.5478] | 0.5478 / 0.5468 / 0.5143 |

**When the model disagrees with the market, the market is usually right.** No tier's hit
rate reaches 0.5 in either sport. The NBA's T3 is the sharpest: on the 36% of games where
the model sits 10 points or more away from the close, the outcome went the model's way
only 35% of the time, and the interval [0.308, 0.400] excludes a coin flip. Section 9
pre-stated that the top tier's edge would shrink out of sample; here it does worse than
shrink. T3 is not empty, so section 9's "may be empty" outcome does not arise. Per-tier
results are exploratory under section 7's family-wise policy.

### Reliability by model-probability bucket (exploratory, NOT section 9)

| bucket | NBA n | NBA mean p / actual | NHL n | NHL mean p / actual [95% CI] |
|---|---|---|---|---|
| [0.00, 0.35) | 241 | 0.2461 / 0.2905 | 79 | 0.2786 / 0.3291 |
| [0.35, 0.45) | 146 | 0.3987 / 0.4315 | 185 | 0.4069 / **0.5243** [0.4486, 0.5946] |
| [0.45, 0.55) | 178 | 0.5024 / 0.5056 | 330 | 0.5034 / 0.5182 |
| [0.55, 0.65) | 194 | 0.5998 / 0.5361 | 301 | 0.5976 / 0.6080 |
| [0.65, 1.00) | 404 | 0.7727 / 0.7624 | 253 | 0.7163 / 0.6877 |

The NHL's [0.35, 0.45) bucket is where its ECE comes from: 185 games forecast at 41% won
52% of the time, an interval excluding the forecast. It is a reliability observation, not
a pre-registered tier, and no model change is made in response.

## 6. The nested test, rehearsed out of sample (section 7)

**Corrected on review, 2026-10-04.** The first version fitted Model B and the
recalibration null on the same dev games it then scored, so every Clark-West number in it
was in-sample and tilted toward B, the larger model. It also gave B only the Elo and rest
difference, unscaled, with missing rest filled as 0. Both are fixed (PREREGISTRATION,
section 7 readings 1 and 3): B now carries the price-free model's own covariates, scaled
and median-filled as the model is, and B and the null are fitted per rolling-origin fold
on that fold's training games and scored on the month after.

### NBA (6 folds)
| closing price | null | CW | p (normal) | p (date bootstrap) | n |
|---|---|---|---|---|---|
| close | identity | -0.334 | 0.6309 | 0.6165 | 1,163 |
| close | **recalibrated (primary)** | **-0.072** | 0.5286 | 0.5105 | 1,163 |
| t1h | identity | -0.368 | 0.6436 | 0.6370 | 1,162 |
| t1h | recalibrated | -0.113 | 0.5449 | 0.5235 | 1,162 |

### NHL (4 folds; 2024-11-01 and 2024-12-01 skipped, no priced games before December)
| closing price | null | CW | p (normal) | p (date bootstrap) | n |
|---|---|---|---|---|---|
| close | identity | -0.055 | 0.5220 | 0.5370 | 717 |
| close | recalibrated | -0.027 | 0.5109 | 0.5265 | 717 |
| t1h | identity | -0.057 | 0.5226 | 0.5395 | 717 |
| t1h | recalibrated | +0.005 | 0.4980 | 0.5075 | 717 |

**Out of sample, Model B adds nothing over the market in either sport, against either
null.** Every CW statistic sits within a few tenths of zero. The first rehearsal's
headline, that the NHL split on the null with B beating the raw price at p 0.0015, was an
in-sample artefact and is withdrawn. On this evidence the pre-registered primary test (B
against the recalibration null, NBA, close, Brier) is expected to find nothing on the
holdout; the holdout is still the only pass that counts.

**This is a rehearsal, not the test.** The pre-registered nested test is one fit on all of
dev and one pass over the sealed holdout, after the model is frozen by commit.

## What the holdout pass still has to fill

- Every table above, recomputed once on 2025-26 through `holdout.open_holdout`, by a
  holdout script that does not exist yet and must be written, reviewed and pushed first.
- Reliability diagrams for the model and the market side by side. Section 6 asks for every
  table **and figure** on dev first, so this figure is cut on dev before the freeze.
- The headline-1 verdict against its pre-stated band: a 0.02-0.03 Brier deficit against
  the market, decomposed and explained.

## Decided before week 9 (2026-10-04)

1. **The model is frozen as it is.** It loses to its own Elo on dev and is worse
   calibrated, and that is reported, not fixed: the pre-registration fixed its form, the dev
   comparison is tilted toward the Elo (Amendment 5b's overlap), and the holdout, where
   the constants were never tuned, is where the comparison becomes fair. After Deviation 1,
   a change now would read as steered.
2. **Headline 1's framing follows the evidence:** on dev, a schedule-and-rating model
   roughly matches its own rating, both trail the market, and adding the model's features
   to the market price adds nothing out of sample.
