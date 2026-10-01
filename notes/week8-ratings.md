# Week 8 — the Elo rating, tuned on dev and frozen

PREREGISTRATION Amendment 5b fixes the model's deterministic pre-game rating before any
model code exists. This is the record it requires: every grid point with its log loss,
published in the same commit that freezes the three constants.

**The order is the mechanism.** K, the home bonus H and the season carry-over c were
chosen by lowest log loss of the Elo win probability over every 2024-25 game, with
2023-24 as burn-in and never in the criterion. They are now constants in
`src/chira/ratings.py` (`CHOSEN`), pinned by a test. No 2025-26 rating has been
computed. Git history is the proof of order.

**2025-26 was not read.** `scripts/run_ratings.py` passes both the criterion set and the
burn-in set through `holdout.assert_dev_only`, which refuses the holdout season and
refuses rows carrying no season at all.

## The burn-in fetch, and the team that changed its name

`scripts/fetch_burnin.py` pulls 2023-24 from the same league sources as the census:
1,230 NBA and 1,312 NHL games, every team exactly 82, into `data/burnin/`, outside the
census store and the snapshot. No 2023-24 price is read anywhere; section 1's exclusion
of that season stands, and these games are never a model row and are never scored.

**`club-schedule-season/UTA/20232024` returns zero games and no error.** The franchise
played 2023-24 as Arizona. The count guard would not have caught it either: every
Arizona game appears in its opponent's schedule, so the enumeration still totals 1,312
and only the team *code* is wrong — 82 games attributed to a team that did not exist and
a Utah rating starting from nothing. The fetch takes `ARI` and renames it to `uta`,
which is exactly Amendment 5b's "Utah inherits Arizona's end-of-2023-24 rating before
the pull": one franchise, one rating, carried across the rename.

Sanity checks that passed: every team exactly 82 games in both leagues, no tied games,
NBA scores 73-157 and NHL 0-10, home win rate 0.5431 (NBA) and 0.5412 (NHL), and
2023-24 NBA opening night reads LAL 107 @ DEN 119 and PHX 108 @ GSW 104.

## The availability rule binds, hard

A game's pre-game rating may only reflect results that were public when it started
(`features.RESULT_DELAY_SECONDS`), the same rule as every other feature. In the feature
store this never bound — a team's own previous game is a day earlier. **Elo is
league-wide**, so an opponent's game three hours earlier the same evening binds
constantly:

| | pairs where a result was not public at the later game's start | games with at least one |
|---|---|---|
| NBA | 5,535 | 1,879 of 2,460 (**76.4%**) |
| NHL | 4,752 | 1,830 of 2,624 (**69.7%**) |

Updates are therefore queued and applied at `start + delay`, not at the earlier game's
tipoff.

## An ambiguity in the amendment, measured rather than argued

Amendment 5b's margin multiplier divides by "the winner's pre-game rating edge", which
does not say whether the home bonus is included. The implementation includes it, matching
the published FiveThirtyEight form the amendment cites, so it is the same quantity that
entered the expectation.

**It does not matter.** Both readings select the same grid point for both sports; the
log-loss gap is 7e-6 (NBA) and 2.2e-5 (NHL). Recorded as `WINNER_EDGE_INCLUDES_H` so the
choice is visible, not because it is consequential.

## The grid

### NBA — 140 grid points

**Chosen: K=20, H=50, c=0.6** → log loss **0.60781**, Brier 0.21044, n=1,230.

Baselines on the same 2024-25 games: a coin flip is 0.69315, the
home base rate (0.5439) is 0.68929. The rating beats the base
rate by **0.08148** log loss. Worst grid point
0.65579, so the grid spans 0.04798.

Best log loss at each value, holding nothing else fixed:

- **K** `10`→0.61410  `15`→0.60942  `20`→0.60781  `25`→0.60790  `30`→0.60898
- **H** `50`→0.60781  `75`→0.61292  `100`→0.62245  `125`→0.63621
- **c** `0`→0.61280  `0.5`→0.60790  `0.6`→0.60781  `0.7`→0.60808  `0.75`→0.60837  `0.8`→0.60875  `0.9`→0.60980

Every point, log loss, best in bold:

| K | H | c=0 | c=0.5 | c=0.6 | c=0.7 | c=0.75 | c=0.8 | c=0.9 |
|---|---|---|---|---|---|---|---|---|
| 10 | 50 | 0.62510 | 0.61536 | 0.61456 | 0.61415 | 0.61410 | 0.61414 | 0.61452 |
| 10 | 75 | 0.63079 | 0.62073 | 0.61989 | 0.61944 | 0.61936 | 0.61939 | 0.61973 |
| 10 | 100 | 0.64108 | 0.63058 | 0.62967 | 0.62916 | 0.62906 | 0.62906 | 0.62937 |
| 10 | 125 | 0.65579 | 0.64471 | 0.64372 | 0.64313 | 0.64300 | 0.64297 | 0.64322 |
| 15 | 50 | 0.61725 | 0.60977 | 0.60942 | 0.60948 | 0.60965 | 0.60993 | 0.61080 |
| 15 | 75 | 0.62274 | 0.61497 | 0.61459 | 0.61461 | 0.61478 | 0.61504 | 0.61589 |
| 15 | 100 | 0.63279 | 0.62461 | 0.62418 | 0.62416 | 0.62431 | 0.62456 | 0.62538 |
| 15 | 125 | 0.64718 | 0.63849 | 0.63799 | 0.63792 | 0.63804 | 0.63828 | 0.63907 |
| 20 | 50 | 0.61385 | 0.60791 | **0.60781** | 0.60808 | 0.60837 | 0.60875 | 0.60980 |
| 20 | 75 | 0.61924 | 0.61305 | 0.61292 | 0.61317 | 0.61344 | 0.61382 | 0.61486 |
| 20 | 100 | 0.62918 | 0.62263 | 0.62245 | 0.62268 | 0.62294 | 0.62331 | 0.62434 |
| 20 | 125 | 0.64344 | 0.63643 | 0.63621 | 0.63639 | 0.63664 | 0.63699 | 0.63802 |
| 25 | 50 | 0.61280 | 0.60790 | 0.60793 | 0.60832 | 0.60865 | 0.60908 | 0.61020 |
| 25 | 75 | 0.61815 | 0.61303 | 0.61304 | 0.61341 | 0.61373 | 0.61415 | 0.61527 |
| 25 | 100 | 0.62806 | 0.62262 | 0.62260 | 0.62295 | 0.62326 | 0.62367 | 0.62479 |
| 25 | 125 | 0.64229 | 0.63645 | 0.63638 | 0.63670 | 0.63701 | 0.63741 | 0.63852 |
| 30 | 50 | 0.61315 | 0.60898 | 0.60909 | 0.60954 | 0.60989 | 0.61032 | 0.61146 |
| 30 | 75 | 0.61850 | 0.61413 | 0.61422 | 0.61465 | 0.61500 | 0.61543 | 0.61656 |
| 30 | 100 | 0.62843 | 0.62378 | 0.62384 | 0.62425 | 0.62459 | 0.62502 | 0.62616 |
| 30 | 125 | 0.64270 | 0.63769 | 0.63771 | 0.63810 | 0.63843 | 0.63885 | 0.63999 |

### NHL — 105 grid points

**Chosen: K=16, H=50, c=0.9** → log loss **0.66618**, Brier 0.23686, n=1,312.

Baselines on the same 2024-25 games: a coin flip is 0.69315, the
home base rate (0.5625) is 0.68531. The rating beats the base
rate by **0.01913** log loss. Worst grid point
0.68059, so the grid spans 0.01441.

Best log loss at each value, holding nothing else fixed:

- **K** `8`→0.66814  `12`→0.66647  `16`→0.66618  `20`→0.66658  `30`→0.66891
- **H** `25`→0.66783  `50`→0.66618  `75`→0.66951
- **c** `0`→0.67373  `0.5`→0.66826  `0.6`→0.66756  `0.7`→0.66696  `0.75`→0.66671  `0.8`→0.66650  `0.9`→0.66618

Every point, log loss, best in bold:

| K | H | c=0 | c=0.5 | c=0.6 | c=0.7 | c=0.75 | c=0.8 | c=0.9 |
|---|---|---|---|---|---|---|---|---|
| 8 | 25 | 0.67828 | 0.67264 | 0.67177 | 0.67098 | 0.67062 | 0.67028 | 0.66966 |
| 8 | 50 | 0.67691 | 0.67118 | 0.67030 | 0.66949 | 0.66912 | 0.66878 | 0.66814 |
| 8 | 75 | 0.68059 | 0.67474 | 0.67383 | 0.67300 | 0.67262 | 0.67226 | 0.67160 |
| 12 | 25 | 0.67648 | 0.67061 | 0.66980 | 0.66910 | 0.66880 | 0.66852 | 0.66806 |
| 12 | 50 | 0.67505 | 0.66908 | 0.66825 | 0.66753 | 0.66722 | 0.66694 | 0.66647 |
| 12 | 75 | 0.67869 | 0.67256 | 0.67170 | 0.67096 | 0.67063 | 0.67034 | 0.66984 |
| 16 | 25 | 0.67557 | 0.66988 | 0.66916 | 0.66858 | 0.66834 | 0.66814 | 0.66783 |
| 16 | 50 | 0.67409 | 0.66830 | 0.66756 | 0.66696 | 0.66671 | 0.66650 | **0.66618** |
| 16 | 75 | 0.67769 | 0.67173 | 0.67096 | 0.67033 | 0.67007 | 0.66985 | 0.66951 |
| 20 | 25 | 0.67525 | 0.66989 | 0.66926 | 0.66878 | 0.66860 | 0.66845 | 0.66827 |
| 20 | 50 | 0.67373 | 0.66826 | 0.66762 | 0.66712 | 0.66693 | 0.66678 | 0.66658 |
| 20 | 75 | 0.67731 | 0.67167 | 0.67099 | 0.67047 | 0.67027 | 0.67010 | 0.66989 |
| 30 | 25 | 0.67606 | 0.67155 | 0.67110 | 0.67080 | 0.67071 | 0.67065 | 0.67065 |
| 30 | 50 | 0.67445 | 0.66985 | 0.66939 | 0.66908 | 0.66898 | 0.66892 | 0.66891 |
| 30 | 75 | 0.67798 | 0.67323 | 0.67274 | 0.67241 | 0.67231 | 0.67224 | 0.67222 |


## Both optima sit on a grid edge, and the grid was not widened

Amendment 5b: *"An optimum on the edge of the grid is reported as a limitation; the grid
is never widened after seeing it."* Both are the strong form of the problem — the
marginal profile is **still improving at the boundary**, so the unconstrained optimum is
outside the grid.

- **NBA H=50 is the grid's floor**, and the H profile is monotone increasing across the
  whole grid (0.60781 → 0.63621). A 50-point bonus implies a 0.5717 home win rate at
  equal ratings against an observed **0.5439**, so the grid's smallest home bonus is
  already larger than the data wants. The cost is bounded: H is the best-behaved
  parameter in the table and the whole H range spans 0.028 log loss.
- **NHL c=0.9 is the grid's ceiling**, and the c profile is monotone decreasing
  (0.67373 → 0.66618). NHL team strength wants to carry across the season boundary
  almost completely; the grid stops just short of letting it.

Neither was widened, and neither will be. The limitation is reported in
`ratings.CHOSEN`'s comment, here, and in the writeup.

## What the numbers say beyond the choice

**The NHL rating barely helps.** It beats the home base rate by 0.019 log loss against
the NBA's 0.081 — four times less — and the entire NHL grid spans 0.014, less than a
third of the NBA's 0.048. That is the same finding week 4 measured from the other side:
NHL Murphy resolution was 0.0055 against the NBA's 0.0517, and a market quoting near the
base rate is pricing a sport whose outcomes are close to coin flips. A rating built from
the same schedule has the same ceiling. It is consistent, and it is a caveat headline 1
will have to carry for the NHL.

**The two sports want different memory.** NBA c=0.6 against NHL c=0.9: roster turnover
moves an NBA team's strength much more between seasons than an NHL team's. Both sit
well above c=0, which is the grid's "fresh start every season" control — carrying a
rating over helps in both sports, and the 2023-24 to 2024-25 change is what decides it,
exactly as the amendment intended.
