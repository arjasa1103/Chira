"""Run one forward-collector session, or a dry run of one.

    uv run python scripts/run_collector.py --dry-run     # week-4 verification
    uv run python scripts/run_collector.py               # a real session

**Nothing here runs live until late October 2026.** The 2026-27 seasons are the
collector's target and the week-4 deliverable is the code plus the pre-season
dry run, not a live capture. `--dry-run` makes no network call at all: it prints
exactly what a real session would decide, which is the part worth checking now
(the ET gates, the heartbeat wiring, the store, and the zero-capture rule).

Exit codes are the alerting contract:
    0  captured something, or correctly no-opped off-season / outside the window
    1  the run should have captured and did not (T14: a zero-capture day must
       fail VISIBLY, because a silent zero is indistinguishable from an outage)
    2  refused to start
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "src")
import chira
from chira.cache import Cache
from chira.census import load_abbr_map, map_fingerprint
from chira.collector import (
    ET,
    CollectorStore,
    Heartbeat,
    active_seasons,
    complement_check,
    describe_plan,
    et_now,
    in_poll_window,
    is_season_active,
    minutes_until_window,
    next_poll_delay,
    poll_target,
    resolve_targets,
    session_deadline,
    upcoming_targets,
    window_is_too_far,
    window_start_for,
    zero_capture_is_a_failure,
)
from chira.http import Client
from chira.telemetry import Telemetry, run_id
from chira.upcoming import nhl_upcoming, parse_start

ABBR = "data/abbr_map_resolved.json"

# How often the target list is rebuilt: markets appear, tipoffs move, and a
# session runs for hours. Cheap next to the polls it feeds.
TARGET_REFRESH_SECONDS = 30 * 60
LOOKAHEAD_DAYS = 3


def abbr_map_path() -> str:
    """The resolver's output if it exists, else the map vendored in the package.

    **`data/` is gitignored, so on a fresh checkout the resolver's output does
    not exist.** Measured the hard way: the first real Actions dispatch
    (run 36481636318, 2026-09-28) died at startup with
    `FileNotFoundError: data/abbr_map_resolved.json`, before polling anything
    and before the heartbeat ping, which is why the monitor stayed silent
    rather than going red loudly. A scheduled session the next night would have
    failed identically, on opening night.

    The vendored copy carries only `map` and `unresolved`, the two keys
    `load_abbr_map` reads. The resolver's `evidence` field is excluded on
    purpose: it holds Polymarket slugs, and this file ships in a public repo.
    A locally resolved map still wins, so re-running the resolver changes
    behaviour here exactly as before.
    """
    local = Path(ABBR)
    if local.is_file():
        return str(local)
    return str(Path(chira.__file__).with_name("abbr_map_collector.json"))


def abbr_map_for(sport: str, season: str) -> tuple[dict, str]:
    """The season's map, or the newest earlier one as a prior. Never silent.

    `load_abbr_map` raises for a season it has never resolved, and 2026-27 has
    not been resolved because the resolver reads a FINISHED schedule. Falling
    back is safe here in a way it would never be in the census: `confirm`
    re-checks both team labels against the market's own outcomes for every
    game, so a translation that has drifted shows up as an unresolved game
    rather than as the wrong market. Measured 2026-09-26: the 2025-26 NHL map
    resolved 47 of 47 upcoming 2026-27 games.
    """
    path = abbr_map_path()
    try:
        return load_abbr_map(path, season, sport), season
    except (KeyError, FileNotFoundError):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        earlier = sorted(k for k, v in (doc.get("seasons") or {}).items()
                         if sport in v and k < season)
        if not earlier:
            raise
        prior = earlier[-1]
        # `path`, not ABBR: this branch is the one 2026-27 actually takes, so
        # reading the gitignored path here reproduced the original crash even
        # after the lookup above was fixed.
        return load_abbr_map(path, prior, sport), prior


# Every schedule state, not only games still to come: a run that arrives while
# the day's matinee is being played must compute the SAME opening as one that
# arrived before it, or the window would jump back to 16:00 mid-afternoon.
ALL_GAME_STATES = ("FUT", "PRE", "LIVE", "CRIT", "OFF", "FINAL")


def first_tip_today(now=None) -> tuple:
    """(today's first start in UTC or None, a note saying where it came from).

    One schedule read per run, before anything is logged, because it decides
    whether this run polls at all. Any failure is None, which `window_start_for`
    turns into the old 16:00 ET opening: a broken schedule read can make the
    window as late as it always was, never later. NBA enumeration is not wired
    yet, so NBA afternoon games do not move the opening until it is.
    """
    today = et_now(now).date()
    try:
        client = Client()
        tips = []
        for sport, _season in (active_seasons() or [("nhl", "2026-27")]):
            if sport != "nhl":
                continue
            for g in nhl_upcoming(client, today, days=1, states=ALL_GAME_STATES):
                if str(g.get("et_date")) == str(today):
                    t = parse_start(g.get("start_time_utc"))
                    if t is not None:
                        tips.append(t)
    # Broad by intent: the fallback is the old fixed window, which is safe.
    except Exception as e:
        return None, f"schedule unreadable ({type(e).__name__}), so 16:00 ET"
    if not tips:
        return None, "no games today, so 16:00 ET"
    return min(tips), "first start today"


def collect_targets(client, tel, days: int = LOOKAHEAD_DAYS
                    ) -> tuple[list[dict], list[dict]]:
    """Enumerate upcoming games for every active season and resolve markets."""
    targets: list[dict] = []
    unresolved: list[dict] = []
    today = datetime.now(UTC).astimezone(ET).date()
    for sport, season in (active_seasons() or [("nhl", "2026-27")]):
        if sport != "nhl":
            # NBA upcoming enumeration is not wired yet; the NBA 2026-27 season
            # tips late October. Recorded rather than silently skipped.
            tel.event("sport_not_wired", sport=sport, season=season)
            continue
        games = nhl_upcoming(client, today, days=days)
        amap, used = abbr_map_for(sport, season)
        if used != season:
            tel.event("abbr_map_fallback", sport=sport, season=season, used=used)
        got, missed = resolve_targets(client, games, amap)
        targets += got
        unresolved += missed
    tel.event("targets_resolved", targets=len(targets), unresolved=len(unresolved))
    return targets, unresolved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="decide everything, touch no network, write nothing")
    ap.add_argument("--store", default="data/collector/live.duckdb")
    ap.add_argument("--cache", default=".http-cache")
    ap.add_argument("--log", default="data/logs/collector.jsonl")
    ap.add_argument("--max-seconds", type=int, default=None,
                    help="override the session length (the default stops short "
                         "of the 6h Actions job cap)")
    ap.add_argument("--once", action="store_true",
                    help="one poll cycle instead of a full session")
    ap.add_argument("--check-windows", action="store_true",
                    help="verify each configured season window against the "
                         "league's real schedule (makes network calls, so it is "
                         "not part of --dry-run)")
    ap.add_argument("--lookahead-days", type=int, default=LOOKAHEAD_DAYS,
                    help="how far ahead to enumerate games; the rehearsal needs "
                         "to reach opening night, a live session does not")
    ap.add_argument("--force", action="store_true",
                    help="poll even when the season or daily gate says no. For "
                         "the pre-season rehearsal: markets list well before "
                         "opening night, so the live path can be proven without "
                         "waiting for the gate to open")
    args = ap.parse_args()

    plan = describe_plan()
    print(json.dumps(plan, indent=2, sort_keys=True))

    if args.check_windows:
        from datetime import timedelta

        from chira.collector import SEASON_WINDOWS
        from chira.upcoming import check_season_window
        probe = Client()
        print("\n=== SEASON WINDOW CHECK (against the league's own schedule) ===")
        bad = 0
        for (sport, season), window in SEASON_WINDOWS.items():
            if sport != "nhl":
                print(f"  {sport} {season}: no upcoming enumerator wired; skipped")
                continue
            got = check_season_window(probe, window[0] - timedelta(days=10), window)
            flag = "ok" if got["covered"] else "WINDOW MISSES OPENING NIGHT"
            bad += 0 if got["covered"] else 1
            print(f"  {sport} {season}: first game {got['first_game']}, "
                  f"window {got['window'][0]}..{got['window'][1]} -> {flag}")
        if bad:
            print("  A window that starts after the opener no-ops through real "
                  "games and looks exactly like a working off-season gate.")
            return 2
        return 0

    if args.dry_run:
        # Report the heartbeat's absence loudly. An unconfigured monitor is the
        # single most likely reason a six-month unattended run dies unnoticed,
        # and it is invisible unless something says so before the season starts.
        if not plan["heartbeat_configured"]:
            print("\nWARNING: no CHIRA_HEARTBEAT_URL set. With no external "
                  "monitor, a collector that never starts reports nothing and "
                  "nobody finds out. Pick a provider before the season opens.")
        print("\ndry run: no network calls made, no rows written")
        return 0

    if not is_season_active() and not args.force:
        # Not a failure. Off-season zero-capture is the correct answer, and
        # failing here would train the reader to ignore red runs.
        print("\noff-season for every configured window: nothing to do")
        return 0
    # Today's opening, from the league schedule: the earlier of 16:00 ET and
    # the first puck drop minus three hours. Computed before the exit check,
    # because a matinee day must not send its morning runs away.
    first_tip, tip_note = first_tip_today()
    start = window_start_for(first_tip)
    tip_et = first_tip.astimezone(ET).strftime("%H:%M ET") if first_tip else "-"
    print(f"\npoll window today opens {start.strftime('%H:%M')} ET "
          f"({tip_note}: {tip_et})")
    if not args.force and window_is_too_far(start=start):
        # The common case now, not an edge: the workflow fires every 30 minutes
        # because GitHub delivers scheduled runs hours late, and most of those
        # runs land far from the window. Exit before the telemetry and the
        # heartbeat: a run that never polled must not tell the monitor a
        # session happened, or the dead-man's switch goes green on nothing.
        print(f"the poll window opens in {minutes_until_window(start=start):.0f} "
              f"min, more than {plan['early_start_minutes']}; exiting so a "
              f"later run takes it. No heartbeat: nothing was collected.")
        return 0
    if args.force:
        print("\n--force: polling regardless of the season and window gates. "
              "This is a rehearsal, not a scheduled run.")

    rid = run_id("collector")
    tel = Telemetry(args.log, rid, {"plan": plan, "seasons": active_seasons()})
    hb = Heartbeat()
    season_for_cache = (active_seasons() or [("nhl", "2026-27")])[0][1]
    client = Client(cache=Cache(args.cache, abbr_version=map_fingerprint(
        abbr_map_for("nhl", season_for_cache)[0])))
    captured = polls = 0
    targets: list[dict] = []
    unresolved: list[dict] = []
    max_due = 0
    last_poll_at: datetime | None = None
    enumeration_ok = True
    last_refresh = -TARGET_REFRESH_SECONDS
    note = ""

    with CollectorStore(args.store) as store:
        store.start_session(rid)
        deadline = session_deadline(max_seconds=args.max_seconds) if args.max_seconds \
            else session_deadline()
        started = time.monotonic()
        try:
            while time.monotonic() < deadline:
                if not in_poll_window(start=start) and not args.force:
                    tel.event("outside_window")
                    if args.once:
                        break
                    if window_is_too_far(start=start):
                        # The window has closed. The old loop slept on to the
                        # 5h30 deadline, holding a runner that the next queued
                        # run was waiting for.
                        tel.event("window_closed")
                        break
                    time.sleep(min(300, max(0, deadline - time.monotonic())))
                    continue
                if time.monotonic() - last_refresh > TARGET_REFRESH_SECONDS:
                    try:
                        targets, unresolved = collect_targets(
                            client, tel, days=args.lookahead_days)
                        enumeration_ok = True
                    # Broad by intent: "could not enumerate" must be recorded as
                    # an outage, not mistaken for a quiet night.
                    except Exception as e:
                        enumeration_ok = False
                        tel.event("enumeration_failed", error=str(e)[:200])
                        print(f"enumeration FAILED: {type(e).__name__}: {e}")
                    last_refresh = time.monotonic()
                # A live session only polls games about to start. A rehearsal
                # has to reach opening night, so --force widens the due window
                # to the whole enumerated range.
                due = (upcoming_targets(targets, lookahead_hours=24 * args.lookahead_days)
                       if args.force else upcoming_targets(targets))
                max_due = max(max_due, len(due))
                last_poll_at = datetime.now(UTC)
                tel.event("poll", targets=len(targets), due=len(due))
                polls += 1
                rows: list[dict] = []
                for t in due:
                    got = poll_target(client, t, poll_seq=polls, run_id=rid)
                    chk = complement_check(got)
                    if chk["checked"] and not chk["ok"]:
                        # The census's invariant, live. A token-leg mix-up is
                        # invisible in the prices themselves and only shows up
                        # here, at capture time.
                        tel.event("complement_failed", slug=t.get("slug"),
                                  sum=chk["sum"])
                    rows += got
                captured += store.put_quotes(rows)
                if args.once:
                    break
                time.sleep(next_poll_delay(time.monotonic() - started))
        except KeyboardInterrupt:
            note = "interrupted"
        finally:
            store.finish_session(rid, captured, polls, note)
            total = store.quote_count()

    # Judged at the last poll, not at exit: sessions now end when the window
    # closes, and judged at exit every one of them would look "outside the
    # window" and pass with nothing captured. `max_due` for the same reason:
    # by the last poll of the night every game has tipped and nothing is due.
    failed = zero_capture_is_a_failure(captured, now=last_poll_at,
                                       targets_due=max_due,
                                       enumeration_ok=enumeration_ok,
                                       start=start)
    if args.force:
        # A rehearsal must never ping the monitor: the dead-man's switch means
        # "a scheduled session ran", and a hand-run one satisfying it would
        # hide a cron that never fired.
        delivered = False
        print("--force: heartbeat deliberately NOT pinged (rehearsal)")
    else:
        delivered = hb.ping(ok=not failed, detail=f"captured={captured}")
    tel.close(captured=captured, polls=polls, heartbeat_delivered=delivered)

    print(f"\nsession {rid}: {polls} polls, {captured} quotes captured, "
          f"{total} in store, {len(targets)} targets, {len(unresolved)} unresolved")
    if unresolved:
        from collections import Counter
        print(f"unresolved reasons: {dict(Counter(u['reason'] for u in unresolved))}")
    print(f"http: {dict(client.stats)}")
    if not delivered and not args.force:
        print(f"heartbeat NOT delivered: {hb.last_error}")
    if failed:
        why = ("enumeration failed, so whether there were games is unknown"
               if not enumeration_ok
               else f"{max_due} games were due and none were captured")
        print(f"FAILING: the season is active, the poll window was open, and "
              f"{why}. This is the outage signal, not a warning.")
        return 1
    if captured == 0:
        print("captured nothing, correctly: "
              + ("off-season or outside the poll window"
                 if not (is_season_active() and in_poll_window(start=start))
                 else "no games were scheduled in the window"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
