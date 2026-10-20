# Wiring NBA upcoming enumeration into the collector

The last open week-7 collector item, due 2026-10-20 because that is the day the
NBA's 2026-27 regular season opens. Pre-game prices cannot be fetched later, so
every day without this is a day of NBA capture lost for good.

## The source: ESPN, because nothing else answers

Re-probed from this machine on 2026-10-20, confirming the 2026-10-01 check:

| source | result |
|---|---|
| `stats.nba.com/stats/scheduleleaguev2` | **connection timeout** (the census reaches it through `nba_api`, and even there it is unreliable) |
| `cdn.nba.com/static/json/staticData/scheduleLeagueV2.json` | **403** |
| `cdn.nba.com/.../liveData/scoreboard/todaysScoreboard_00.json` | **403** |
| `data.nba.com/prod/v1/20261020/scoreboard.json` | **403** |
| `site.api.espn.com/.../nba/scoreboard?dates=20261020` | **200**, 3 games |

Browser headers, referer and origin on every attempt. ESPN is the only source
that answers, so `constants.ESPN_NBA_API` is it, and the module treats ESPN's
data as third-party rather than as the league's own — which is the one place
this differs from `nhl_upcoming`, where the league itself answers.

## The ET date is the date requested, not the timestamp

The same trap `nhl_upcoming` documents, in a different shape. ESPN groups games
by US calendar day, so San Antonio's 21:30 ET tipoff arrives under
`dates=20261020` carrying `date: 2026-10-21T01:30Z`. Deriving the ET date from
that timestamp would slug the whole late slate a day forward and find no market.

Proven end to end: that game stored as `nba-okc-sas-2026-10-20`, with a real
Polymarket midpoint (0.515 / 0.485, complementary).

This is why the module makes **one request per day** instead of using ESPN's
`dates=A-B` range form. A range response gives no per-day attribution, so it
would force exactly the derivation that breaks.

## Six abbreviations differ, and the map is vendored

ESPN writes `GS`, `NO`, `NY`, `SA`, `UTAH`, `WSH` where the census writes `gsw`,
`nop`, `nyk`, `sas`, `uta`, `was`. The other 24 are identical once lowercased.

`scripts/fetch_espn_nba_codes.py` re-derives the map from ESPN's own `/teams`
endpoint, diffs it against the 30 codes in `data/abbr_map_resolved.json`, and
exits non-zero on any disagreement. Run 2026-10-20: **all 30 translate, 6 need
translating, 24 identical.** Vendored rather than fetched for the reason the
venue table and the neutral-site list are vendored: a translation table that can
change under the collector mid-season fails *silently*, because a drifted code
resolves no market and the day looks like "Polymarket had not listed it yet".

**One subtlety worth its three lines of code.** ESPN writes the Clippers' city as
`LA` and the Lakers' as `Los Angeles`. `resolve.team_labels` accepts a place name
only when it is unique in the league, precisely so a Lakers/Clippers slug cannot
confirm with the two sides swapped — and two different spellings both look
unique, re-admitting place-level matching for exactly the pair the guard exists
to protect. `ESPN_PLACE_FIXES` collapses them, and a test asserts the guard then
drops `Los Angeles` from both teams' labels.

## ESPN's tipoff time is not trusted past its own deadline

`collector.upcoming_targets` drops a game 30 minutes after its scheduled tipoff.
So a time that is wrong *early* does not degrade capture, it **ends** it: four
hours early, and the four most valuable hours of pre-game prices are gone and
cannot be refetched.

The 2026-10-01 source check flagged exactly this risk — ESPN published BOS@DET at
19:00Z, "3:00 PM EDT", on a slate whose other two games were 19:00 and 21:30 ET,
and that looked like a placeholder.

So `nba_upcoming` returns `start_time_utc: None` when a game's scheduled time is
more than 20 minutes past and ESPN still reports it as not started. That is not a
special case bolted on: `upcoming_targets` already **keeps** games whose start
time is unknown, by documented design, and `live_quotes.secs_to_tipoff` is
nullable. A game ESPN reports as `in` or `post` keeps its time, because starting
corroborates the clock with something other than itself.

**The suspicion turned out to be wrong, and the guard is still worth having.**
BOS@DET tipped at 19:00Z. Observed directly at 19:16:43Z: `STATUS_IN_PROGRESS`,
first quarter, 6:39 on the clock, Detroit 13 Boston 11. The NBA really did
schedule a 3:00 PM ET opener, ESPN's time was correct, and the guard did not fire
today — 0 of 15 captured NBA games had a null tipoff. It stays because the
failure it prevents is silent and irreversible, not because it has caught
anything. Recorded this way so nobody later reads it as a fixed bug.

That also answers the checklist's "verify tipoff times against a second source"
better than a second schedule feed could: the second source was the game.

## What the window does now

`first_tip_today` reads both leagues, so an NBA matinee moves the opening exactly
as an NHL one does. Measured on the live run: the window opened **12:00 ET**
against a 15:00 ET first start, where before today it would have opened at 16:00
— an hour after that game tipped.

`check_season_window` dispatches on sport instead of scanning the NHL schedule
whatever it was asked. It still raises for a sport with no enumerator, which is
the property that mattered: a checker that can quietly validate the wrong league
is worse than no checker. Live, both windows pass:

```
nba 2026-27: first game 2026-10-20, window 2026-10-15..2027-04-20 -> ok
nhl 2026-27: first game 2026-10-20, window 2026-09-20..2027-04-30 -> ok
```

## The end-to-end run

`scripts/run_collector.py --once --force --lookahead-days 3`, writing to a
scratch store, 2026-10-20T19:14Z:

```
40 targets, 0 unresolved, 80 quotes captured, 80 in store
http: {'http:200': 204}
```

15 NBA games and 25 NHL, two sides each. **0 unresolved**, with the NBA on the
2025-26 abbreviation fallback — which is the evidence the week-7 fallback item
asked for before accepting it for the NBA.

The sixteenth enumerated NBA game is BOS@DET, correctly absent: it had already
started, so it is no longer `pre`.

## What was lost, and what was not

**BOS@DET's pre-game prices are gone.** The collector had no NBA path while that
game was listed, and nothing can refetch them. One game.

PHI@NY (23:00Z) and OKC@SA (01:30Z) were still ahead when this landed, and the
rehearsal run has already stored quotes for both.

## Still open

- **Unproven from GitHub Actions.** ESPN answers from this machine; Actions runs
  from a datacentre IP, which is what 403s `cdn.nba.com` and times out
  `stats.nba.com`. `gh workflow run collector.yml -f dry_run=false -f once=true`
  on this branch is the proof, and it needs the branch pushed.
- **`check_season_window` is weak once a season is running.** It reports the
  first *upcoming* game, so mid-season it answers "today" for both leagues
  rather than the season's real opener. Pre-existing; it only validates a window
  before the season starts.
- **The NBA abbreviation fallback** is accepted on this evidence (15/15 resolved,
  0 unresolved for a reason other than no_market). Reopen if any unresolved
  reason other than `no_market` appears.
