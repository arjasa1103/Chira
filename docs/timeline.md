# Timeline

Living document. Plan calendar against what actually happened, plus the dates ahead that
cannot move. Companion to [checklist.md](checklist.md), which tracks the work itself.

**Deadline: 2026-11-30.** Last updated 2026-10-05.

---

## Where the project stands

| | |
|---|---|
| Plan weeks complete | 7 of 11. Weeks 8-9: model built and frozen as is (decided 2026-10-04), dress rehearsal on dev done and corrected; reliability diagrams and the holdout script are what remain before the holdout opens |
| Calendar position | Week 8 starts on the plan's calendar 2026-11-03 |
| Slack | About 5 weeks ahead |
| Days to deadline | 56 |
| Binding constraint | Fixed dates, not effort |
| Collector | **Live since 2026-09-28.** Every NHL game from 09-29 to 10-04 has pre-game prices; the window opens 3 h before the first game since 10-02. GitHub's late, sparse delivery is covered by hand-dispatch reminders on early days until the collector moves to the Chira-gamble runner |
| Unpushed | `2d2cf67` (forecast log), `54ecb12` (Stage 1a kill), `26a0c83` (TODOS), `090f6b3` (review: the corrected prize figure) |

---

## Plan against actual

The plan's calendar started 2026-09-15. Work began earlier and ran faster, so every row
landed ahead of its window.

| Plan week | Scheduled window | Landed | Ahead by | What shipped |
|---|---|---|---|---|
| 1 | Sep 15-21 | **2026-09-11** | 10 days | Rate-limit probe, abbreviation maps, noise floor, pre-registration |
| 2 | Sep 22-28 | **2026-09-12** | 16 days | HTTP layer, cache, store, census runner, validation gate |
| 3 | Sep 29-Oct 5 | **2026-09-13** | 22 days | Full census of 5,084 games, immutable snapshot |
| 4 | Oct 6-12 | **2026-09-16** | 26 days | Charts 1 and 2, synthetic scorer, collector, Amendment 2 |
| 5 | Oct 13-26 | **2026-09-21** | 35 days | Headline 2, the primary test, Amendments 3 and 4 |
| 6 | Oct 13-26 | **2026-09-25** | 31 days | Artifact v1 published, prior art, reproduction path |
| 7 | Oct 27-Nov 2 | **2026-09-27** | 30 days | Collector live path (09-26); feature store, `game_prices`, venue table, leakage canary (09-27) |
| 8-9 | Nov 3-16 | **in progress** | — | Preconditions 09-28/29. **Elo frozen 10-01** (`d66671c`), 2025-26 ratings built, **model fitted on dev** (`f447287`, converges both sports). **Deviation 1**: 2025-26 Elo scores seen before the seal. Next: rolling origins, sensitivity, GBM, dress rehearsal, holdout opened once |
| 10-11 | Nov 17-30 | not started | — | Headline 1 added as artifact v2 |

---

## Dates that cannot move

Being ahead buys nothing against these. Two are league schedules, one is a platform change.

| Date | What | Why it is fixed | Status |
|---|---|---|---|
| ~~2026-09-29~~ | NHL 2026-27 opened (FLA@CAR, 21:00Z) | The league's schedule | **Done.** Hand dispatch at 20:01Z; all five games captured from pre-game to tipoff |
| **every game night** | NHL slate, first puck drops 23:00Z on most nights | The league's schedule | Hand dispatch at 19:55Z (16:55 ADT) until the new schedule proves itself |
| **2026-10-19** | `ubuntu-latest` migrates to Ubuntu 26 | GitHub Actions runner change | Tracked as P3 in TODOS |
| **2026-10-20** | NBA 2026-27 regular season opens | The league's schedule | **NBA enumeration not wired**: the collector captures nothing NBA until it is |
| **late Oct** | Availability source can first be proven (E7) | Needs live games with injury reports | Week-7 timebox, not started |
| **2026-11-30** | Hard deadline | Semester | 60 days out |

### The collector, night by night

GitHub delivered the two original crons 3h22 to 6h02 late every night. The fix
(`294dcd3`, pushed 2026-10-01 13:47Z) fires every 30 minutes at :17 and :47. Each run
decides for itself: it polls inside the window, waits if the window opens within 45
minutes, and otherwise exits at once without pinging. Sessions end when the window closes
and hand over through the concurrency group.

| Night (ET) | Run | Started | Late by | Result |
|---|---|---|---|---|
| 09-28 | `0 20` | 00:08Z | 4h08 | 66 polls, 0 captured (no games), correct |
| 09-28 | `45 1` | 07:30Z | 5h45 | 0 polls, entirely outside the window |
| **09-29** | **hand dispatch** | **20:01Z** | — | **492 quotes, all 5 opener games, every 5 min from 20:01Z** |
| 09-29 | `0 20` | 23:22Z | 3h22 | Queued behind the dispatch; caught VAN@EDM and CHI@VGK through tipoff (60 quotes) |
| 09-29 | `45 1` | 07:26Z | 5h41 | 0 polls |
| 09-30 | `0 20` (no dispatch) | 23:23Z | 3h23 | 98 quotes. **PIT@PHI and NYI@TOR got 7 minutes of pre-game data**; T-6h and T-1h lost for good. LAK@COL fine |
| 09-30 | `45 1` | 07:47Z | 6h02 | 0 polls |
| 10-01 | **new schedule, no dispatch** | 19:35Z | — | **All 8 games from 20:00Z to puck drop, 928 quotes.** Waited for the opening, ran to its cap at 01:05:57Z; the queued run took over at 01:06:07Z and stopped at window close (06:31Z). Two later runs exited in seconds, no ping. Only 4 of ~46 slots delivered in 23 h |
| 10-02 | window opening from the schedule | — | — | Shipped: the opening moves to first puck drop minus 3 h (never later than 16:00 ET). Tonight opens 15:30 ET for NYR@DET 18:30. **Sun 10-04 opens 10:00 ET for WPG@DET 13:00**, the first matinee; check it was polled |
| 10-02 to 10-04 | 23 games | — | 77-109 min | All 23 NHL games with pre-game prices to puck drop (3,636 quotes). First runs arrived 77 min (Fri) and 109 min (Sat) after the opening; **Sunday's 13:00 ET matinee was saved by a hand dispatch** (the first scheduled run came 37 min after puck drop) |
| 10-10 to 10-25 | reminders | — | — | Hand-dispatch reminders on all 8 early-opening days, until the collector moves to the Chira-gamble runner |

Every artifact is copied to `data/collector-archive/` (gitignored): Actions keeps them 90
days and runs do not accumulate. Re-run the download loop after each game night.

**Two follow-ups from the schedule change:**

- **Healthchecks: done 2026-10-01.** Period 1 day, grace 6 hours, because sessions now end
  at window close (~06:30Z) and pings can be about 19 hours apart.
- **Hand dispatch stays the safety net** (tonight's is scheduled) until one night shows the 30-minute schedule covering
  the window on its own. A dispatch only joins the queue, so it is safe alongside a
  scheduled session.

```bash
gh workflow run collector.yml -f dry_run=false -f once=false
```

Every night the collector misses is forward data that cannot be backfilled, because
`/midpoint` and `/book` only answer for markets that still exist.

---

## What the remaining weeks hold

**Week 8 (in progress).** The Elo rating landed 2026-10-01 as `d66671c`, pushed the same
day before any 2025-26 rating existed ([notes/week8-ratings.md](../notes/week8-ratings.md)):

- **Frozen:** NBA K=20 H=50 c=0.6, log loss 0.60781; NHL K=16 H=50 c=0.9, log loss 0.66618.
  Both optima sit on a grid edge, which is disclosed, and the grid was not widened.
- **2023-24 warm-up season fetched in full.** Utah's 2023-24 schedule had to be fetched
  as Arizona, because the league returns zero Utah games for that season.
- **Review fixes** (`334b09c`): a silently ignored delay override now works; the frozen
  log losses are pinned by a CI golden test and a real-data recompute; the rating has its
  own leakage canary with a must-fail form; the NBA neutral-site fix lives inside the
  walk; the seal's scope is written down (earlier results are features, the seal guards
  scoring).
- **Decisions before the first fit, done** (`0a75bc0`): the model takes
  `rating_diff_strength` and owns home advantage itself (third reading of 5b); Brier stays
  primary, with the reason in PLAN.md. The missing-travel fill lands with the model.
- **The seal, finished in code** (`0a75bc0` plus the review fix `70c0aee`): the marker is
  pushed before any label, `is_open` reads the remote, and a push that does not land rolls
  back instead of spending the holdout with nothing released. **Branch protection is on**
  (ruleset `protect-main`, 2026-10-01): deletions and force-pushes blocked, nothing else, so
  the marker push still lands. The seal is complete.
- **Prior art:** SSRN 5910522 read by hand 2026-10-01. No liquidity split, no NBA or NHL,
  so the contribution stands. v1's one stale line is corrected when v2 publishes.

**The model and the dress rehearsal (2026-10-01 to 10-04).** The hierarchical logistic converges
on dev for both sports. **Deviation 1** (PREREGISTRATION.md): the first 2025-26 ratings run
printed the Elo's 2025-26 scores for both sports before the seal was open; scoring the sealed
season is now refused in code. The dress rehearsal on 2024-25
([notes/week8-model.md](../notes/week8-model.md)), as corrected on review 2026-10-04:

- **Out of sample the model loses to its own Elo** (NBA Brier 0.2125 vs 0.2097) and is
  worse calibrated. Frozen as it is: the pre-registration fixed its form, and the holdout,
  where the Elo's constants were never tuned, is where the comparison becomes fair.
- **The black-box benchmark (T17) does worse still**, so interpretability costs nothing here.
- **Model B adds nothing over the market**, in either sport, against either null, once fitted
  out of sample per fold on the model's own covariates. The first rehearsal's in-sample
  "NHL p 0.0015" is withdrawn.
- **Section 9's risk tiers:** no tier's hit rate reaches 0.5; when the model disagrees with
  the close by 10 points or more, the market is right about two times in three.

**Before the holdout opens:** reliability diagrams on dev, then `scripts/run_holdout.py`,
reviewed and pushed. That push is the freeze.

**Weeks 8-9.** The model, then a full dress rehearsal on 2024-25 producing every table and
figure, then the 2025-26 holdout opened exactly once. The holdout is a one-way door, and
being ahead of schedule is not a reason to open it before the model is frozen.

**Weeks 10-11.** Headline 1 added to the published artifact as v2.

**The profit track** moved to a private repository, Chira-gamble, on 2026-10-01, pinning this
repo by commit. **Its Stage 1a gate killed Signal L on 2026-10-05**
([notes/profit-stage1-verdict.md](../notes/profit-stage1-verdict.md)): the bet-time liquidity
proxy correlates 0.25 with volume against a pre-committed 0.5, because it mostly measures how
long a market was listed. Headline 2 stands as a description; what died is trading it through
that proxy. Vendor spend ceiling: $0.

---

## How to keep this current

Update the "landed" column when a week's commit lands on `main`, and re-check the fixed
dates against the leagues rather than against this table:

```bash
uv run python scripts/run_collector.py --check-windows
```

That command scans the real schedule and fails loudly if a configured season window opens
after the league's first game, which is the exact bug week 7 found.
