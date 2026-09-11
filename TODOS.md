# TODOS

Deferred work, with enough context to pick up cold. Sourced from the /autoplan
CEO review (2026-09-11). Items in PLAN.md's task list are NOT duplicated here.

## P2 — Soccer / tennis / cricket extension

**What:** Extend the census and calibration pipeline to the sports whose Polymarket
coverage was confirmed dense but which sit outside the two-sport scope.

**Why:** Coverage was verified during design probing: a single Jan-2026 window held 116
`nhl-` slugs plus soccer draw markets across `epl`, `elc`, `ere`, `mex`, `spl`, `por`,
`tur`, and cricket under `crind` / `craus`. Soccer especially gives thousands of matches
a season with free xG data from FBref and Understat.

**Pros:** The pipeline is sport-agnostic by design, so marginal cost is an adapter plus an
abbreviation map. More sports strengthen the cross-sport calibration claim, which is the
component with a guaranteed positive result.

**Cons:** Soccer is three-way (draws), so it needs a multinomial scoring path rather than
binary Brier. Cricket and lower-tier soccer markets are thin.

**Context:** Slug convention is `<league>-<away>-<home>-<YYYY-MM-DD>` with a US-Eastern
date, same as NBA/NHL. The abbreviation map must be learned per league per season. Start
from `ingest/abbr.py` once T3 lands.

**Effort:** M (human) → S (with CC). **Priority:** P2.
**Depends on:** PLAN.md T3 (per-season abbreviation map), T7 (snapshot release).

## P2 — Multinomial scoring path for three-way markets

**What:** Generalize `scoring/` from binary Brier/log-loss to the multiclass case.

**Why:** Required by the soccer extension above; soccer draw markets make outcome a
three-way variable. Ranked probability score becomes relevant, though Wheatcroft (2022)
recommends Brier and log loss over RPS even there.

**Pros:** Unlocks the largest-volume sport on Polymarket. Murphy decomposition generalizes.

**Cons:** Calibration curves and edge tiers need rethinking for 3 classes; the
home-side-only convention does not transfer.

**Effort:** M (human) → S (with CC). **Priority:** P2.
**Depends on:** the soccer extension being accepted.

## P3 — In-game / live market analysis

**What:** Analyze how prices move *during* games rather than only pre-tipoff.

**Why:** The minute-level series continues through the game (the probed Grizzlies/Kings
market ran to 06:47 UTC, well past the 02:00 tipoff). That is a full intra-game probability
path, free, already collected by the census.

**Pros:** Zero extra collection cost, it is already in the snapshot. Intra-game win
probability is a well-studied problem with public baselines to compare against.

**Cons:** Different question, different labels, and needs play-by-play joined on game clock.
Would double the project's scope if pulled into the main line.

**Context:** Explicitly out of scope for the calibration project. Revisit only after the
historical half ships.

**Effort:** L (human) → M (with CC). **Priority:** P3.
**Depends on:** T7 (snapshot release) containing full post-tipoff series.

## P3 — Kelly staking / equity-curve simulation

**What:** Translate edge tiers into fractional-Kelly stake sizes and plot an equity curve.

**Why:** It was considered and rejected during design (D6) because it depends on calibration
being proven first, and because it pushes the project toward a staking tool rather than a
measurement instrument.

**Pros:** The most persuasive single chart if, and only if, a real edge is established.

**Cons:** Meaningless before calibration is proven. Invites over-reading a backtest. The
project explicitly contains no bet-placement system and should stay that way.

**Context:** Only revisit if the nested test returns a significant positive result under
both closing-price constructions. If it returns null, this item is dead, not deferred.

**Effort:** S (human) → S (with CC). **Priority:** P3.
**Depends on:** a positive nested-test result.
