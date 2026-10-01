# Timeline

Living document. Plan calendar against what actually happened, plus the dates ahead that
cannot move. Companion to [checklist.md](checklist.md), which tracks the work itself.

**Deadline: 2026-11-30.** Last updated 2026-10-01.

---

## Where the project stands

| | |
|---|---|
| Plan weeks complete | 7 of 11. Week 8 in progress: the Elo rating is frozen (2026-10-01), the model is not started |
| Calendar position | Week 8 starts on the plan's calendar 2026-11-03 |
| Slack | About 5 weeks ahead |
| Days to deadline | 60 |
| Binding constraint | Fixed dates, not effort |
| Collector | **Live since 2026-09-28.** Opening night fully captured by hand dispatch. Schedule rebuilt 2026-10-01 for the 3-6 h cron lag; the new schedule has not fired yet |
| Unpushed | Three commits: the rating review fixes and seal-scope note (`334b09c`), the week-8 decisions and the seal's rewind bypass (`0a75bc0`), and the checklist (`f42bd0b`). The freeze itself (`d66671c`) is public since 2026-10-01 |

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
| 8-9 | Nov 3-16 | **in progress** | — | Preconditions 09-28/29 (Amendment 5, neutral sites, holdout seal). **Elo rating frozen and pushed 10-01** (`d66671c`). Next: the model, the dress rehearsal, the holdout opened once |
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
| 10-01 | new schedule | — | — | No run delivered by 17:30Z, 3h40 after the push. Expected at this lag; watch for the first one |

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
- **Review fixes, uncommitted:**
  - a delay override that was silently ignored now works;
  - the frozen log losses are now actually pinned, by a CI golden test plus a recompute
    from the real data;
  - the rating has its own leakage canary, with a must-fail form;
  - the NBA neutral-site fix now lives inside the rating walk;
  - the holdout seal's scope is written down: inputs from earlier results are features,
    and the seal guards scoring.

**Before the first model fit:**

- Decide which term carries home advantage. The rating difference includes the home
  bonus, and the model plan has its own home term.
- Brier as the primary score, with the reason.
- The missing-travel fill.

**Before week 9 opens the holdout:**

- **Close the residual seal bypass.** Reproduced 2026-10-01: after one open,
  `git reset --hard HEAD~1` deletes the local marker commit and a second open returns the
  labels again, leaving nothing on GitHub. The fix pushes the marker before any label is
  returned, makes `is_open` check the remote, and needs branch protection against
  force-pushes.

The dev agent has week 8's remaining items, in order, in the checklist.

**Weeks 8-9.** The model, then a full dress rehearsal on 2024-25 producing every table and
figure, then the 2025-26 holdout opened exactly once. The holdout is a one-way door, and
being ahead of schedule is not a reason to open it before the model is frozen.

**Weeks 10-11.** Headline 1 added to the published artifact as v2.

**The profit track** moved to a private repository, Chira-gamble, on 2026-10-01. It pins
this repo by commit. Its Stage 1a pre-commitment is public here
(`notes/profit-stage1-spec.md`, `e2001ca`), and its own rule is that it pauses if this
semester work misses a gate.

---

## How to keep this current

Update the "landed" column when a week's commit lands on `main`, and re-check the fixed
dates against the leagues rather than against this table:

```bash
uv run python scripts/run_collector.py --check-windows
```

That command scans the real schedule and fails loudly if a configured season window opens
after the league's first game, which is the exact bug week 7 found.
