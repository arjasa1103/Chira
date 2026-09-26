# Week 7 — the collector's live path, proven, and a window that would have missed opening night

The collector was built in week 4 and had never polled a market. This closes that, three
days before it matters.

**The headline finding is a date.** `collector.SEASON_WINDOWS` had the NHL 2026-27 season
opening **2026-10-01**. The league's own schedule opens it **2026-09-29** (fla@car, 21:00Z).
A collector with that window would have returned "off-season, nothing to do" through the
first two nights of the season and exited 0 every time — the exact failure the gate exists
to prevent, inverted, and invisible because a correct off-season no-op looks identical.
Found by enumerating the real schedule rather than by reading the constant.

## What now works

`scripts/run_collector.py` enumerates, resolves and polls for real:

| Stage | Result, measured 2026-09-26 |
|---|---|
| Enumerate upcoming games | 47 NHL games over 7 days, in **one** request |
| Resolve markets | **47 of 47** with the 2025-26 abbreviation map |
| Poll a market | midpoint, best bid/ask with sizes, spread, last trade, book clock |
| Complementarity, live | 1.0000 on every pair checked |
| Rehearsal session | 18 targets, 36 rows written, 3 unresolved (`no_market`) |

The three unresolved are all 2026-09-30 games whose markets were not listed yet. They are
recorded with every slug tried, not dropped, so "not listed yet" stays distinguishable from
"we never tried the right slug".

## Why the census's schedule code could not be reused

`nhl.nhl_games` keeps only `gameState in ("OFF", "FINAL")` with two scores and enforces
exactly 1,312 games, because it builds a **backtest denominator**. Point it at 2026-27 today
and it returns nothing, or raises. Forward capture needs the complement, so `upcoming.py`
exists rather than a flag that would make the census's guards conditional.

**The ET-date rule bites harder here than in the census.** `/schedule/{date}` returns a
seven-day `gameWeek` where each day carries its own `date`, and the individual game objects
have **`gameDate: null`**. Deriving the date from `startTimeUTC` instead would have been
wrong for **21 of 47 games (45%)** in the opening week: a 21:30 ET puck drop is 01:30Z the
next calendar day, so those slugs would have been a day late and found no market.

## The live book is not sorted best-first

Measured on `nhl-phi-nj-2026-10-01`: bids arrive **ascending** (0.01 first, 0.43 last) and
asks **descending** (0.99 first, 0.45 last). "The first level" is the worst price on both
sides. `parse_book` already used min/max so it was right by construction, and it agrees with
Gamma's own `bestBid`/`bestAsk` (0.43/0.45). `book_depth` takes size from whichever level is
actually best, and is tested against the measured payload so a future refactor that reaches
for `bids[0]` fails.

**Depth is thin, which is the capacity question the profit-track doc raised.** Top of book on
opening-night markets is 30-530 units at a 1-2 cent spread. That is a number to plan against,
not a footnote.

**One field is not what it looks like.** `last_trade_price` came back **identical for both
tokens** on 3 of 3 markets (0.44/0.44, 0.46/0.46, 0.49/0.49) while the midpoints differed and
complemented correctly. It is therefore probably market-level rather than side-specific. It
is stored, and it must not be read as "the last trade on this side" until that is verified.

## A false alarm, created and then removed

Widening the NHL window to 2026-09-20 to cover the opener created nine in-season days with no
games. The old rule — season active **and** window open **and** zero captured — would have
failed every one of them and pinged the monitor's `/fail`. Alarm fatigue is how a real outage
gets ignored, so `zero_capture_is_a_failure` now takes the denominator:

- captured something: fine;
- off-season or outside the window: fine;
- **enumeration failed: OUTAGE**, because "no games" and "could not find out" must not look
  the same, and a schedule endpoint returning nothing is exactly how a silent outage survives
  a season;
- enumeration fine and nothing was due: a quiet night, reported as such;
- games were due and nothing was captured: outage.

`--check-windows` re-checks every configured window against the league's real schedule, and
`tests/test_collector.py` pins the measured openers (NHL 2026-09-29, NBA 2026-10-20) so a
future edit cannot narrow a window back past one.

## Rehearsal, and why it does not ping the monitor

`--force` polls regardless of the gates, for exactly this pre-season case: markets list well
before opening night, so the path can be proven without waiting. It **deliberately does not
ping the heartbeat**, because the dead-man's switch means "a scheduled session ran", and a
hand-run session satisfying it would hide a cron that never fired.

## Still open

- **`CHIRA_HEARTBEAT_URL` is not set.** The switch is unarmed and the season opens in three
  days. This is the single most urgent item in the project.
- **The cron is still commented out** in `.github/workflows/collector.yml`, by design: it is
  enabled after the secret exists and one real session has been read.
- **NBA enumeration is not wired.** Only NHL has an upcoming-games source; the NBA 2026-27
  regular season opens 2026-10-20, so there is time, and the session logs `sport_not_wired`
  rather than skipping silently.
- **2026-27 has no resolved abbreviation map.** The 2025-26 map is used as a prior and
  resolved 47 of 47, with `confirm` re-checking both team labels per game so a drifted
  translation surfaces as an unresolved game rather than as the wrong market. The fallback is
  logged as `abbr_map_fallback` every session.
