# Week 5 — headline 2: the market's calibration is liquidity-dependent

Run against the frozen snapshot `census-20260913-224d6ad985e0` plus the week-5 volume side
table. Everything here is reproducible with:

```bash
uv run python scripts/run_headline2.py --reps 2000
```

which writes `docs/charts/headline2.json` and `docs/charts/chart3-headline2.png`.

**`--reps 2000` is part of the command, not decoration.** The flag defaults to 4000, and
every interval below was cut at 2,000, so the bare command reproduces the same point
estimates against different CI digits (the primary CI closes at +1.0399 instead of +1.0325).
The seed is fixed, so with the flag the numbers reproduce exactly.

**The result, in one line.** In NBA games, the Cox calibration slope is **+1.398 in
low-liquidity games and +0.586 in high-liquidity games; the difference is +0.812 with a 95%
game-bootstrap CI of [+0.618, +1.033]**, on n = 1,148 / 1,146. No replicate reproduced the
opposite sign, so the achieved significance level is **< 0.0005**, the floor at 2,000
replicates rather than a measured zero (it is a bootstrap ASL, computed under the observed
distribution, not a null-hypothesis p-value). Thin
markets are *underconfident* (prices sit too near 0.50 for what follows) and liquid markets
are *overconfident* (prices too extreme). This is the pre-registered primary test and it is
not a null.

## What the design does, and why each piece is there

Strata are the pre-registered 2x2 (PREREGISTRATION.md section 8, Amendments 3a/3b/4), with
both axes cut as equal-count medians **inside each sport-season**:

| Sport-season | week median | volume median, early | volume median, late | no volume |
|---|---|---|---|---|
| NBA 2024-25 | 13 | $216,662 | $383,193 | 0 |
| NBA 2025-26 | 13 | $1,765,497 | $2,478,575 | 161 |
| NHL 2024-25 | 18 | $38,376 | $80,082 | 0 |
| NHL 2025-26 | 13 | $469,215 | $791,663 | 157 |

The phase cut needed pinning: section 8 says "2 season phases" and never defines them.
Reproducing Amendment 3a's own table fixed the definition — an equal-count median split on
`week_of_season` with ties going early, and liquidity as a median split **within** each
phase, returns 3a's published figures exactly (pre-registered early share 0.686 / 0.660 /
0.719 / 0.695, within-phase 0.511 / 0.503 / 0.506 / 0.534, cells 221-312). Recorded in
Amendment 4 so it is not re-derived by guess. One discrepancy, stated rather than smoothed:
my Spearman correlations come out 0.005 lower than 3a's in the third decimal
(+0.519/+0.360/+0.537/+0.409 against +0.521/+0.361/+0.532/+0.413).

## The primary test

| | slope | n |
|---|---|---|
| low liquidity | +1.3978 | 1,148 |
| high liquidity | +0.5863 | 1,146 |
| **difference (low − high)** | **+0.8115** | 95% CI **[+0.6178, +1.0325]** |

Zero failed bootstrap replicates out of 2,000. Per season, secondary but independent:
2024-25 **+0.7410** [+0.4641, +1.0360] and 2025-26 **+0.9109** [+0.6169, +1.2408]. Both
exclude zero on their own.

## Every robustness split points the same way

| Split | difference | 95% CI | excludes zero |
|---|---|---|---|
| close (primary) | +0.8115 | [+0.6121, +1.0326] | yes |
| T-1h | +0.8256 | [+0.6204, +1.0143] | yes |
| T-6h | +0.8339 | [+0.6334, +1.0428] | yes |
| T-24h | +0.8528 | [+0.6385, +1.0835] | yes |
| stale closes only | +0.8655 | [+0.5822, +1.1948] | yes |
| fresh closes only | +0.7699 | [+0.5107, +1.0545] | yes |

The four time-to-close looks are four looks at **one** sample, so they are reported as four
intervals and never combined into one; a single interval across them would be too narrow by
construction (section 8).

## The artifact that could have explained it away, tested

Volume is outcome-correlated — section 8 says so plainly, because close games attract
volume. That predicts high-liquidity games sit nearer 0.50, and they do:

| | sd(logit p) | share inside [0.35, 0.65] |
|---|---|---|
| low liquidity | 1.207 | 0.315 |
| high liquidity | 0.949 | 0.507 |

A Cox slope fitted over a narrower price range attenuates toward zero, so **the whole
contrast could have been a range effect rather than a calibration difference.** Three checks:

| Check | difference | 95% CI | excludes zero |
|---|---|---|---|
| restricted to p in [0.20, 0.80] | +0.6588 | [+0.3585, +0.9527] | yes |
| restricted to p in [0.35, 0.65] | +0.5124 | [−0.1902, +1.3290] | **no** |
| caliper-matched on \|logit p\|, 917 pairs | +0.8040 | [+0.5591, +1.0568] | yes |

The matched version equalises the spread almost exactly (sd 0.595 against 0.593) and returns
+0.804, statistically indistinguishable from the unmatched +0.812. **The contrast is not a
price-range artifact.** In the narrowest band the point estimate keeps its sign (+0.512) but
the interval opens up, which is what an underpowered test looks like (n falls to 362/581 and
the price range is nearly flat), not a contradiction.

## The 16 cells, each against the null at its own n

| Cell | n | slope | null slope 95% band | ECE | null ECE p99 | resolution |
|---|---|---|---|---|---|---|
| NBA 2024-25 early/low | 316 | +1.269 | [0.760, 1.319] | 0.0510 | 0.0991 | 0.0634 |
| NBA 2024-25 early/high | 315 | +0.726 | [0.760, 1.319] | 0.0666 | 0.0991 | 0.0311 |
| NBA 2024-25 late/low | 299 | **+1.494** | [0.696, 1.417] | 0.0829 | 0.1299 | 0.1075 |
| NBA 2024-25 late/high | 299 | **+0.563** | [0.696, 1.417] | 0.0817 | 0.1299 | 0.0196 |
| NBA 2025-26 early/low | 321 | +1.276 | [0.760, 1.319] | 0.0503 | 0.0991 | 0.0719 |
| NBA 2025-26 early/high | 320 | **+0.303** | [0.760, 1.319] | 0.1071 | 0.0991 | 0.0091 |
| NBA 2025-26 late/low | 212 | **+1.769** | [0.696, 1.417] | 0.0962 | 0.1299 | 0.1300 |
| NBA 2025-26 late/high | 212 | +0.826 | [0.696, 1.417] | 0.0673 | 0.1299 | 0.0356 |
| NHL 2024-25 early/low | 227 | +1.059 | [0.414, 1.694] | 0.0639 | 0.1288 | 0.0234 |
| NHL 2024-25 early/high | 226 | +0.721 | [0.414, 1.694] | 0.0762 | 0.1288 | 0.0170 |
| NHL 2024-25 late/low | 222 | +1.389 | [0.382, 1.767] | 0.0811 | 0.1414 | 0.0259 |
| NHL 2024-25 late/high | 221 | +0.947 | [0.382, 1.767] | 0.0594 | 0.1414 | 0.0190 |
| NHL 2025-26 early/low | 333 | +0.907 | [0.470, 1.605] | 0.0790 | 0.1118 | 0.0152 |
| NHL 2025-26 early/high | 332 | +0.229 | [0.470, 1.605] | 0.0881 | 0.1118 | 0.0050 |
| NHL 2025-26 late/low | 244 | +1.377 | [0.414, 1.694] | 0.0665 | 0.1288 | 0.0219 |
| NHL 2025-26 late/high | 244 | +0.846 | [0.414, 1.694] | 0.0873 | 0.1288 | 0.0170 |

**Low exceeds high in all 8 sport-season x phase pairs**, NHL included, which is the
strongest thing in the table: eight independent subsamples, one direction. Bold entries fall
outside their own null band.

**Read the null column before reading any single cell.** At NHL n=225 a perfectly calibrated
market's ECE p99 is 0.1288, four times the pooled cap of 0.03, and its slope can land
anywhere in [0.414, 1.694]. Per-cell calibration at this n is close to unfalsifiable, so the
result lives in the pooled contrast and its interval, not in any one cell.

## Two estimator bugs found, both in week-1 machinery

**1. The Cox fit reported failure on converged fits.** Week 4 added a damped line search and
judged convergence on the undamped Newton step against 1e-10. At the optimum, floating-point
noise makes a full step look like it worsens the log-likelihood, so the search shrank the
step scale to 1e-6, the parameters stopped moving, and the step floored at 1.367e-10 — just
above the tolerance. Measured on an NHL bootstrap replicate at n=225: the iterate sat exactly
on the MLE (slope +2.11450 against scipy's +2.114498, gradient 1.1e-9) and the estimator
raised "did not converge" anyway. Convergence is now judged on the **gradient**, the actual
optimality condition. Rate was 1 in 1,500 — and because `simulate_null` had no failure
handling, that one replicate killed an entire null derivation.

That fix needed a second: testing the gradient first reported "converged" with **slope 0.0**
whenever a slope was not identified at all (constant price, or all-identical outcomes),
because the intercept-only start already has a near-zero gradient there. Identifiability is
now an explicit precondition, so those cases raise instead of returning a fabricated zero.

**2. `simulate_null` was fatal on one unfittable replicate, and silently biasable.** It now
counts failures, keeps every fit-free metric on the full set of replicates, and **raises** if
the failure rate exceeds 1% rather than returning slope bands conditioned on convergence.

Effect on already-published numbers: none at four decimals. Largest change anywhere on
re-cutting charts 1 and 2 was 3.45e-05.

## The volume gap: what it actually was

Amendment 3c adopted event-level volume as a proxy for the 318 games with no volume. Week 5
measured that proxy and **withdrew it** (Amendment 4). Two separate problems hid under one
symptom:

- **8 NBA games on 2024-11-12/13 were never missing volume at all.** Their moneyline market
  carries `volumeClob` of $113k-$433k; `census._volume` tried only `volumeNum` and `volume`.
  On 7 normal games where both exist, `volumeClob` equals the stored volume **exactly**
  (ratio 1.000), so reading it recovers the pre-registered quantity rather than substituting
  another. `_volume` now tries it last, so no existing row can change.
- **318 games in 2026-03-04..25 have no per-market volume anywhere.** Confirmed against
  `/events?slug=`, `/markets/{id}` and `/markets?condition_ids=` (which returns empty).
  Event-level volume exists on only ~36% of them and reads **$350-$11,169** against season
  medians of $604k and $2.03M — two to three orders of magnitude off. 3c had assumed event
  volume sums every market type and is therefore an upper bound; it is not. Using it would
  have labelled late-season games low-liquidity on an artifact of the field's meaning, which
  is the confound 3a exists to remove, with the wrong sign.

All 326 games resolved **from the week-3 HTTP cache**, so these are census-time values, which
is what the frozen definition specifies. The side table is
`data/volume_patch/volume_patch.parquet` with its own checksum manifest naming the base
snapshot digest; the frozen snapshot is untouched.

**What the exclusion costs, stated:** the liquidity axis loses 318 late-season games, all in
2025-26 (weeks 20-23 NBA, 22-25 NHL). NBA 2025-26's late cells hold 212 games against 321
early. Those games remain in the phase axis and in every unstratified number.

## Designated P1 tests: 6 of 7 covered

Covered by existing tests: label agreement, shuffled-join, non-JSON 200, cache invalidation,
ET/DST boundary, closing-price extraction. **The leakage canary has no test and cannot have
one yet** — it guards the feature store's point-in-time `as_of` machinery, which is week 7.
Recorded rather than left looking done.

## What this result is NOT

- **Not blind.** Amendment 3c's disclosure stands: candidate designs were evaluated with Cox
  slope point estimates visible on real outcomes, so the direction was known to the author
  before this ran. What was genuinely untested until now: every interval, the phase axis, the
  per-cell structure, the sensitivity splits, and the range-artifact checks.
- **Not causal, and not about profit.** "Thin markets are underconfident" is a description of
  calibration. Nothing here prices a bet or nets a fee, and no strategy follows from it.
- **Conditioned on an outcome-correlated variable.** Terminal volume is mutable and correlates
  with how close a game turns out. The caliper match removes the price-range channel but not
  every path from outcome to volume.
- **Not a per-cell claim.** See the null column.
- **Not the artifact.** Week 6 is the writeup, the dataset release (still gated on the
  Polymarket ToS question), the prior-art section and GitHub Pages.
