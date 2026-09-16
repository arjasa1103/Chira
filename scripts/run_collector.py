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

sys.path.insert(0, "src")
from chira.collector import (
    CollectorStore,
    Heartbeat,
    active_seasons,
    describe_plan,
    in_poll_window,
    is_season_active,
    next_poll_delay,
    session_deadline,
    upcoming_targets,
    zero_capture_is_a_failure,
)
from chira.telemetry import Telemetry, run_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="decide everything, touch no network, write nothing")
    ap.add_argument("--store", default="data/collector/live.duckdb")
    ap.add_argument("--log", default="data/logs/collector.jsonl")
    ap.add_argument("--max-seconds", type=int, default=None,
                    help="override the session length (the default stops short "
                         "of the 6h Actions job cap)")
    ap.add_argument("--once", action="store_true",
                    help="one poll cycle instead of a full session")
    args = ap.parse_args()

    plan = describe_plan()
    print(json.dumps(plan, indent=2, sort_keys=True))

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

    if not is_season_active():
        # Not a failure. Off-season zero-capture is the correct answer, and
        # failing here would train the reader to ignore red runs.
        print("\noff-season for every configured window: nothing to do")
        return 0

    rid = run_id("collector")
    tel = Telemetry(args.log, rid, {"plan": plan, "seasons": active_seasons()})
    hb = Heartbeat()
    captured = polls = 0
    note = ""

    with CollectorStore(args.store) as store:
        store.start_session(rid)
        deadline = session_deadline(max_seconds=args.max_seconds) if args.max_seconds \
            else session_deadline()
        started = time.monotonic()
        try:
            while time.monotonic() < deadline:
                if not in_poll_window():
                    tel.event("outside_window")
                    if args.once:
                        break
                    time.sleep(min(300, max(0, deadline - time.monotonic())))
                    continue
                # The live poll needs a resolved market per upcoming game. That
                # path is deliberately NOT stubbed in: it shares the census's
                # schedule + slug + resolve machinery, and wiring it against
                # 2026-27 schedules that do not exist yet would be untested code
                # pretending to be tested. See notes/week4-charts.md.
                targets = upcoming_targets([])
                tel.event("poll", targets=len(targets))
                polls += 1
                rows: list[dict] = []
                captured += store.put_quotes(rows)
                if args.once:
                    break
                time.sleep(next_poll_delay(time.monotonic() - started))
        except KeyboardInterrupt:
            note = "interrupted"
        finally:
            store.finish_session(rid, captured, polls, note)
            total = store.quote_count()

    failed = zero_capture_is_a_failure(captured)
    delivered = hb.ping(ok=not failed, detail=f"captured={captured}")
    tel.close(captured=captured, polls=polls, heartbeat_delivered=delivered)

    print(f"\nsession {rid}: {polls} polls, {captured} quotes captured, "
          f"{total} in store")
    if not delivered:
        print(f"heartbeat NOT delivered: {hb.last_error}")
    if failed:
        print("FAILING: the season is active and the poll window was open, but "
              "nothing was captured. This is the outage signal, not a warning.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
