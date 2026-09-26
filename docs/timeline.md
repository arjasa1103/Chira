# Timeline

Living document. Plan calendar against what actually happened, plus the dates ahead that
cannot move. Companion to [checklist.md](checklist.md), which tracks the work itself.

**Deadline: 2026-11-30.** Last updated 2026-09-26.

---

## Where the project stands

| | |
|---|---|
| Plan weeks complete | 6 of 11, plus part of week 7 |
| Calendar position | Week 6 was due 2026-10-26; it landed 2026-09-25 |
| Slack | About 4.5 weeks ahead |
| Days to deadline | 65 |
| Binding constraint | Two fixed dates, not effort |

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
| 7 | Oct 27-Nov 2 | **partial** | — | Collector live path done 2026-09-26; feature store not started |
| 8-9 | Nov 3-16 | not started | — | Model, dress rehearsal, holdout opened once |
| 10-11 | Nov 17-30 | not started | — | Headline 1 added as artifact v2 |

---

## Dates that cannot move

Being ahead buys nothing against these. Two are league schedules, one is a platform change.

| Date | What | Why it is fixed | Status |
|---|---|---|---|
| **2026-09-29** | NHL 2026-27 opens (FLA@CAR, 21:00Z) | The league's schedule. Verified against `api-web.nhle.com` on 2026-09-26 | Collector cron still commented out |
| **2026-10-19** | `ubuntu-latest` migrates to Ubuntu 26 | GitHub Actions runner change | Tracked as P3 in TODOS |
| **2026-10-20** | NBA 2026-27 regular season opens | The league's schedule | NBA enumeration not wired |
| **late Oct** | Availability source can first be proven (E7) | Needs live games with injury reports | Week-7 timebox, not started |
| **2026-11-30** | Hard deadline | Semester | 65 days out |

**The nearest one is three days away.** Everything the collector needs is built and the
heartbeat secret is set; the cron in `.github/workflows/collector.yml` is the only step
left, and every night it stays commented out is forward data that cannot be backfilled,
because `/midpoint` and `/book` are forward-only.

---

## What the remaining weeks hold

**Week 7 (in progress).** Half done. The collector's live path landed early because it was
date-driven. The feature store half has not started: point-in-time assembly with `ASOF JOIN`
(verified available on duckdb 1.5.5), rest days, back-to-backs and travel distance. Two
unscheduled prerequisites sit inside it, both filed as P1: travel distance has no data source
in the repo at all, and the narrow `game_prices` table (T15) should land with the feature
store rather than after it.

**Weeks 8-9.** The model, then a full dress rehearsal on 2024-25 producing every table and
figure, then the 2025-26 holdout opened exactly once. The holdout is a one-way door, and
being ahead of schedule is not a reason to open it before the model is frozen.

**Weeks 10-11.** Headline 1 added to the published artifact as v2.

---

## How to keep this current

Update the "landed" column when a week's commit lands on `main`, and re-check the fixed
dates against the leagues rather than against this table:

```bash
uv run python scripts/run_collector.py --check-windows
```

That command scans the real schedule and fails loudly if a configured season window opens
after the league's first game, which is the exact bug week 7 found.
