# Stage 1a verdict: KILL

**Signal L is dead.** Kill criterion 1 decided it, on the first gate, and the spec allows no
appeal: *"rho < 0.5 → the proxy is unfit and 1a fails. No second proxy is tried on this
data."*

Verdict due 2026-10-06 per [the spec](profit-stage1-spec.md); delivered 2026-10-05.
Reproduce with `uv run python scripts/run_stage1a_rho.py`; the numbers are in
`data/stage1a/rho-nba-2024-25.json`.

| | |
|---|---|
| Proxy | count of price changes, market open → T−6h, home side |
| Gate | Spearman rho(count, terminal volume) ≥ 0.5 on NBA 2024-25 |
| **Measured rho** | **0.2467** |
| **Verdict** | **KILL** |
| Games usable for rho | 1,216 of 1,229 (0 excluded for absent volume) |
| Cut (NBA 2024-25 median count) | 158 |
| Misclassification vs headline 2's volume strata | **37.6%** |

Of 1,216 games, the proxy would have put **more than a third into the wrong stratum**. A coin
flip misclassifies 50%, so the proxy is doing something, just not nearly enough: headline 2's
effect is a difference between two strata, and assigning 38% of games to the wrong one dilutes
the thing being traded toward the pooled average, which headline 2 already showed is
approximately nothing.

## Why it failed, measured

The change count is largely a measure of **how long the market had been listed**, not how
actively it traded:

| | rho |
|---|---|
| count vs **listed hours** | **0.5816** |
| count vs raw point count | 0.5810 |
| listed hours vs terminal volume | 0.1021 |
| count vs terminal volume *(the gate)* | 0.2467 |

The count correlates more than twice as strongly with listing duration as with volume, and
listing duration is itself nearly unrelated to volume. Listed hours to T−6h run from **0.0 to
1,823** (76 days) with a median of 86.6 — so one game's count is accumulated over three days
and another's over eleven weeks, and the comparison between them is mostly calendar, not
liquidity.

That is a construction defect, not bad luck. It was foreseeable from the spec alone and was
not foreseen.

## What is NOT being done, on purpose

**No second proxy is being tried.** Changes per listed hour is the obvious repair, it is one
line, and the spec forbids it here: *"No second proxy is tried on this data."* That clause is
the only thing that made the gate worth writing down. Testing repairs against the same 1,216
games until one clears 0.5 would produce a number with no evidential value, and it would be
indistinguishable from what this project spent weeks 4 and 5 building machinery to prevent.

The legitimate route, if Signal L is to be revisited, is a fresh pre-commitment with a
different proxy, fixed before it meets data that has not been used here, and the only such
data is **live 2026-27**. The spec's own framing already says so: *"Only live 2026-27 paper
trading is [blind]."*

## What this does and does not say about headline 2

**Headline 2 is untouched.** It is a descriptive finding about the market's calibration
conditioned on terminal volume, it is published, and it stands: NBA thin markets
underconfident at Cox slope +1.398, liquid markets overconfident at +0.586, difference +0.812
with a 95% CI of [+0.618, +1.033]. Nothing here contradicts any of it.

What is dead is the claim that the finding is **tradeable through this proxy**. The
conditioning variable is terminal volume, which does not exist until after the game, and the
one bet-time substitute Stage 1a pre-committed to does not track it well enough to carry the
split.

For completeness, the upper bound the signal was chasing, computed on dev with terminal-volume
strata and the spec's own cost model and settlement rule: ROI **+0.115**, 90% date-clustered CI
[+0.017, +0.220], 447 bets, at the pass/kill cell (2c half-spread, published fee). That is the
prize that the proxy failed to reach, not a result. It is quoted here so the size of the loss
is on the record, and it is **not** evidence of anything tradeable: it conditions on
information unavailable at bet time.

## Sizing, fire rate, Stage 2 ceiling

Section 8 asks for these. With the signal killed on gate 1 they are moot, and recording them
as if they meant something would be worse than recording the kill:

- **Sizing:** not computed. There is no bet-time stratum to size against.
- **Fire rate:** not computed, for the same reason. The 200-NBA-bets-by-mid-April test is not
  reached.
- **Stage 2 vendor spend ceiling: $0.** The ceiling was to be set against the sizing. There is
  no sizing, so no spend is justified, and the gate exists precisely so that this decision is
  made before money is committed rather than after.

## The one thing that worked

The pre-commitment did its job. The gate was fixed on 2026-10-01 with a committed timestamp,
the proxy was specified before it was computed, the threshold was a number rather than a
judgement, and the kill took one script and no argument. The cost of finding out was a day.
