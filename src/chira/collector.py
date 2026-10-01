"""The forward prices-only collector (Phase 6, built week 4, runs from late Oct 2026).

**Prices only.** The availability / late-news hypothesis is NOT collected here and
is not pre-registered (PREREGISTRATION.md section 10): its source is unproven and
week 7 has one timeboxed slot to prove it. If that slot fails, this collector is
what remains, and it must be useful on its own.

Five things this module exists to get right, each one a failure the plan named:

1. **Quota, not latency, is the binding constraint.** The original 5-10 minute
   polling plan was ~130 runs/day x ~180 days, which exceeds the free Actions
   allowance: the collector would have died of quota in month two, and the plan
   would have modelled the wrong failure. So a poll SESSION is one long-running
   job that loops internally, chained 2-3 times a day, rather than many short
   runs.
2. **The season and daily windows are EASTERN concepts.** A UTC cron clips the
   first or last game of the slate whenever the ET offset shifts, which is the
   same DST bug class already fixed for slugs. The cron is pinned in UTC because
   that is all GitHub offers, and the real gate is computed here in
   America/New_York.
3. **Absence of data is the failure mode, and it is silent.** A dropped cron, an
   auto-disabled workflow, an expired token: all of them look like "no rows
   today". A run that captures nothing while the season is active exits NON-ZERO,
   and `Heartbeat` pings an external monitor that alerts on the ping's ABSENCE.
   Nothing inside this repo can detect its own failure to run.
4. **Two polls can land in the same minute.** Retries, chained jobs overlapping
   at a boundary, and a clock that is not monotonic across runs all produce it.
   Every row carries a `dedup_key`, so a re-poll REPLACES rather than
   double-counting.
5. **The capture time is data, not metadata.** `captured_at` is recorded per row
   so staleness is measurable after the fact. A quote of unknown age cannot be
   used to test anything about timing.

`/midpoint` and `/book` are forward-only: they return "No orderbook exists" once
a market resolves, which is exactly why this data cannot be backfilled and the
collector has to start before the season does.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from .constants import CLOB
from .resolve import confirm, team_labels

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# Season windows in ET dates, deliberately generous at both ends: a window that
# closes too early loses the games it exists to collect, and an extra no-op day
# costs one API call to the schedule. Pre-season and play-in are included.
#
# **These are hand-entered and were wrong once.** The NHL window originally
# opened 2026-10-01; the league's own schedule puts the first 2026-27
# regular-season game on **2026-09-29** (fla@car, 21:00Z), so the collector
# would have no-opped through the first two nights of the season -- the exact
# failure the gate exists to prevent, inverted. Verified against the leagues on
# 2026-09-26: NHL regular season opens 2026-09-29, NBA runs 2026-10-20 to
# 2027-04-11. The NBA window opens 2026-10-15, five days before that first
# game. NBA preseason (2026-10-03 to 10-16) is therefore mostly OUTSIDE the
# window and is not a capture target; only its last two days fall inside. An
# earlier version of this comment claimed the preseason was covered, which it
# never was.
# `upcoming.check_season_window` re-checks this against the live schedule, and
# tests/test_collector.py pins the measured dates.
SEASON_WINDOWS: dict[tuple[str, str], tuple[date, date]] = {
    ("nba", "2026-27"): (date(2026, 10, 15), date(2027, 4, 20)),
    ("nhl", "2026-27"): (date(2026, 9, 20), date(2027, 4, 30)),
}

# The first regular-season date each league actually scheduled, measured
# 2026-09-26. A window that starts after one of these loses opening night.
MEASURED_FIRST_GAME = {("nhl", "2026-27"): date(2026, 9, 29),
                       ("nba", "2026-27"): date(2026, 10, 20)}

# The ET clock window a session polls in. It SPANS MIDNIGHT: a 22:30 ET tipoff on
# the west coast is still being quoted at 01:00 ET the next calendar day, and a
# window expressed as start < end would silently drop those games.
POLL_START_ET = dtime(16, 0)
POLL_END_ET = dtime(2, 30)

# One GitHub Actions job is capped at 6 hours. A session stops short of that on
# purpose: a job killed at the cap loses its final writes and, worse, never runs
# its own failure reporting, so the run looks like a success that captured less.
SESSION_MAX_SECONDS = 5 * 3600 + 30 * 60
POLL_INTERVAL_SECONDS = 300

# How close to the window a run may start and still wait for it. Measured
# 2026-09-28/30: scheduled runs arrive 3h22-5h45 late, so no fixed cron can aim
# at 16:00 ET. The workflow fires every 30 minutes instead and each run decides
# for itself: within this many minutes of the window it waits, further out it
# exits at once, holding no runner and pinging nobody. Above the 30-minute cron
# spacing so that, lags permitting, some run always lands inside it.
EARLY_START_MINUTES = 45

# Live midpoints are quoted to the tick, so the two sides sum to 1 only up to
# rounding; the census's 1e-6 is for settled series, not for a live book.
COMPLEMENT_LIVE_TOL = 0.02

HEARTBEAT_ENV = "CHIRA_HEARTBEAT_URL"
HEARTBEAT_TIMEOUT = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_quotes (
    dedup_key   TEXT NOT NULL,
    sport       TEXT NOT NULL,
    season      TEXT NOT NULL,
    game_id     TEXT NOT NULL,
    slug        TEXT,
    token_id    TEXT NOT NULL,
    side        TEXT NOT NULL,   -- 'home' | 'away'
    captured_at TIMESTAMPTZ NOT NULL,
    midpoint    DOUBLE,
    best_bid    DOUBLE,
    best_ask    DOUBLE,
    spread      DOUBLE,
    -- Depth at top of book, plus the venue's own book clock. Size is why this
    -- is worth storing: the underconfidence headline 2 found lives in thin
    -- markets, and "is there anything to trade against" is a size question
    -- that a price series cannot answer.
    best_bid_size    DOUBLE,
    best_ask_size    DOUBLE,
    last_trade_price DOUBLE,
    book_timestamp   TEXT,
    -- Re-read every poll, never cached: a postponed game's tipoff moves, and a
    -- stale target keeps polling a market whose game already started (T18).
    game_start_time TIMESTAMPTZ,
    secs_to_tipoff  BIGINT,
    poll_seq    INTEGER NOT NULL,
    run_id      TEXT NOT NULL,
    PRIMARY KEY (dedup_key)
);

CREATE TABLE IF NOT EXISTS sessions (
    run_id      TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    captured    INTEGER,
    polls       INTEGER,
    note        TEXT,
    PRIMARY KEY (run_id)
);
"""


def midpoint_url(token_id: str) -> str:
    return f"{CLOB}/midpoint?token_id={token_id}"


def book_url(token_id: str) -> str:
    return f"{CLOB}/book?token_id={token_id}"


def et_now(now: datetime | None = None) -> datetime:
    """Current time in ET. Accepts an injected `now` so the gates are testable.

    A naive datetime is rejected rather than assumed: the whole point of this
    module is that an unlabelled wall-clock time is how the DST bugs got in.
    """
    if now is None:
        return datetime.now(UTC).astimezone(ET)
    if now.tzinfo is None:
        raise ValueError("refusing a naive datetime; pass an aware one")
    return now.astimezone(ET)


def active_seasons(now: datetime | None = None,
                   windows: dict | None = None) -> list[tuple[str, str]]:
    """Which (sport, season) pairs are in season RIGHT NOW, by ET date."""
    today = et_now(now).date()
    return [key for key, (lo, hi) in (windows or SEASON_WINDOWS).items()
            if lo <= today <= hi]


def is_season_active(now: datetime | None = None, windows: dict | None = None) -> bool:
    """T18's date gate. Outside every window the cron must no-op, not poll.

    Without this the workflow burns quota all summer and, more importantly,
    "captured nothing" stops being a signal: a zero-capture day in July is
    correct and a zero-capture day in January is an outage, and the dead-man's
    switch cannot tell them apart unless the collector knows the difference.
    """
    return bool(active_seasons(now, windows))


def in_poll_window(now: datetime | None = None) -> bool:
    """True inside the ET evening window, which spans midnight."""
    t = et_now(now).timetz().replace(tzinfo=None)
    if POLL_START_ET <= POLL_END_ET:
        return POLL_START_ET <= t <= POLL_END_ET
    return t >= POLL_START_ET or t <= POLL_END_ET


def minutes_until_window(now: datetime | None = None) -> float:
    """0 inside the poll window, else minutes until it next opens.

    Measured in UTC, not by subtracting two ET wall-clock times: aware datetimes
    that share a tzinfo subtract as naive ones, which is an hour wrong across a
    DST change.
    """
    n = et_now(now)
    if in_poll_window(n):
        return 0.0
    # Outside the window it is between POLL_END_ET and POLL_START_ET on the
    # same ET date, so the next opening is today's.
    opens = datetime.combine(n.date(), POLL_START_ET, tzinfo=ET)
    if opens <= n:
        opens += timedelta(days=1)
    return (opens.astimezone(UTC) - n.astimezone(UTC)).total_seconds() / 60


def window_is_too_far(now: datetime | None = None,
                      early_minutes: int = EARLY_START_MINUTES) -> bool:
    """Should a run outside the window stop instead of waiting for it?

    True at a start far from the window (a late cron at 07:30 UTC) and at a
    session's end once the window has closed. Either way waiting would hold a
    runner for hours and then ping success for a session that polled nothing,
    which is what the old `45 1` slot did every night.
    """
    return minutes_until_window(now) > early_minutes


def dedup_key(sport: str, season: str, token_id: str, captured_at: datetime) -> str:
    """Stable key at one-second resolution.

    Second, not minute: two polls a few seconds apart around a retry are
    DIFFERENT observations worth keeping, while a re-poll of the same second is
    the duplicate this exists to collapse. The hash keeps the key short and the
    inputs are all in it, so it is reproducible from the row itself.
    """
    if captured_at.tzinfo is None:
        raise ValueError("captured_at must be timezone-aware")
    stamp = captured_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    raw = f"{sport}|{season}|{token_id}|{stamp}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _num(value: Any) -> float | None:
    """Prices arrive as strings. Never coerce a failure into 0.0."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    # isfinite rejects NaN and +/-inf together; a self-comparison NaN check
    # reads as a typo and lint flags it.
    return out if math.isfinite(out) else None


def parse_book(payload: Any) -> dict:
    """Best bid/ask from a `/book` response.

    A resolved market returns "No orderbook exists" rather than an empty book,
    and an empty book is also legitimate pre-open. Both come back as None here,
    which is recorded, not treated as a zero price.
    """
    if not isinstance(payload, dict):
        return {"best_bid": None, "best_ask": None, "spread": None}
    bids = payload.get("bids") or []
    asks = payload.get("asks") or []
    bid = max((v for v in (_num(b.get("price")) for b in bids
                           if isinstance(b, dict)) if v is not None), default=None)
    ask = min((v for v in (_num(a.get("price")) for a in asks
                           if isinstance(a, dict)) if v is not None), default=None)
    spread = None if bid is None or ask is None else round(ask - bid, 6)
    return {"best_bid": bid, "best_ask": ask, "spread": spread}


def book_depth(payload: Any) -> dict:
    """Size at top of book, last trade, and the venue's own book timestamp.

    Kept separate from `parse_book` on purpose: that function answers "what is
    the price", this one answers "how much is there and how fresh is it", and
    the two have different failure modes. A resolved market returns no book at
    all, which is None everywhere rather than zero size.
    """
    out = {"best_bid_size": None, "best_ask_size": None,
           "last_trade_price": None, "book_timestamp": None}
    if not isinstance(payload, dict):
        return out
    bids = [b for b in (payload.get("bids") or []) if isinstance(b, dict)]
    asks = [a for a in (payload.get("asks") or []) if isinstance(a, dict)]
    # The live book is NOT sorted best-first: measured 2026-09-26, bids arrive
    # ascending and asks descending, so "the first level" is the WORST price on
    # both sides. Size is taken from whichever level actually is the best.
    best_bid = max((_num(b.get("price")) for b in bids
                    if _num(b.get("price")) is not None), default=None)
    best_ask = min((_num(a.get("price")) for a in asks
                    if _num(a.get("price")) is not None), default=None)
    if best_bid is not None:
        out["best_bid_size"] = sum(_num(b.get("size")) or 0.0 for b in bids
                                   if _num(b.get("price")) == best_bid) or None
    if best_ask is not None:
        out["best_ask_size"] = sum(_num(a.get("size")) or 0.0 for a in asks
                                   if _num(a.get("price")) == best_ask) or None
    out["last_trade_price"] = _num(payload.get("last_trade_price"))
    ts = payload.get("timestamp")
    out["book_timestamp"] = str(ts) if ts not in (None, "") else None
    return out


def quote_row(*, sport: str, season: str, game_id: str, slug: str | None,
              token_id: str, side: str, captured_at: datetime,
              midpoint: Any, book: Any, game_start_time: datetime | None,
              poll_seq: int, run_id: str) -> dict:
    """One captured quote, ready to insert."""
    secs = None
    if game_start_time is not None:
        if game_start_time.tzinfo is None:
            raise ValueError("game_start_time must be timezone-aware")
        secs = int((game_start_time - captured_at).total_seconds())
    return {
        "dedup_key": dedup_key(sport, season, token_id, captured_at),
        "sport": sport, "season": season, "game_id": game_id, "slug": slug,
        "token_id": token_id, "side": side,
        "captured_at": captured_at.astimezone(UTC),
        "midpoint": _num(midpoint.get("mid") if isinstance(midpoint, dict) else midpoint),
        **parse_book(book),
        **book_depth(book),
        "game_start_time": (None if game_start_time is None
                            else game_start_time.astimezone(UTC)),
        "secs_to_tipoff": secs,
        "poll_seq": poll_seq, "run_id": run_id,
    }


_COLS = ("dedup_key", "sport", "season", "game_id", "slug", "token_id", "side",
         "captured_at", "midpoint", "best_bid", "best_ask", "spread",
         "best_bid_size", "best_ask_size", "last_trade_price", "book_timestamp",
         "game_start_time", "secs_to_tipoff", "poll_seq", "run_id")


class CollectorStore:
    """Append-only quote store, deliberately NOT the census store.

    Separate file and separate schema: the census is a frozen, reconciled
    artifact and this is a growing log written unattended for months. Mixing
    them would put an append-only writer inside the file every downstream
    result is hashed against.

    **This file must never be committed.** PLAN.md is explicit about it, and
    `data/` is gitignored; the workflow uploads it as a build artifact instead.
    """

    def __init__(self, path: str | Path = "data/collector/live.duckdb") -> None:
        p = Path(path)
        if p.parent != Path():
            p.parent.mkdir(parents=True, exist_ok=True)
        self.db = duckdb.connect(str(p))
        self.db.execute("SET TimeZone='UTC'")
        self.db.execute(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> CollectorStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def put_quotes(self, rows: list[dict]) -> int:
        """INSERT OR REPLACE on dedup_key, in one transaction."""
        if not rows:
            return 0
        vals = [[r.get(c) for c in _COLS] for r in rows]
        self.db.execute("BEGIN TRANSACTION")
        try:
            self.db.executemany(
                f"INSERT OR REPLACE INTO live_quotes ({','.join(_COLS)}) "
                f"VALUES ({','.join('?' * len(_COLS))})", vals)
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        return len(rows)

    def start_session(self, run_id: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO sessions (run_id, started_at) VALUES (?, now())",
            [run_id])

    def finish_session(self, run_id: str, captured: int, polls: int,
                       note: str = "") -> None:
        self.db.execute(
            "UPDATE sessions SET finished_at = now(), captured = ?, polls = ?, "
            "note = ? WHERE run_id = ?", [captured, polls, note, run_id])

    def captured_today(self, now: datetime | None = None) -> int:
        """Rows captured on the current ET date, which is the unit alerting uses."""
        today = et_now(now).date()
        return self.db.execute(
            "SELECT count(*) FROM live_quotes "
            "WHERE CAST(captured_at AT TIME ZONE 'America/New_York' AS DATE) = ?",
            [today]).fetchone()[0]

    def quote_count(self) -> int:
        return self.db.execute("SELECT count(*) FROM live_quotes").fetchone()[0]


def _with_query(url: str, extra: str) -> str:
    """Append a query parameter, respecting a URL that already has one."""
    return f"{url}{'&' if '?' in url else '?'}{extra}"


# How each provider is told "the run succeeded" and "the run failed".
#
# These are NOT interchangeable, which an earlier draft of this module got
# wrong by assuming every provider accepts `<url>/fail`:
#
#   healthchecks  <url> on success, <url>/fail on failure. A real failure
#                 channel, so an outage is reported the moment it is known
#                 rather than waiting out the grace period.
#   cronitor      state is a query parameter, not a path segment. Appending
#                 /fail to a Cronitor URL pings a telemetry endpoint that does
#                 not exist and the check stays green while the run is broken.
#   betterstack   heartbeats have NO failure path. Silence is the only signal,
#                 so a failed run must NOT ping at all -- pinging on failure
#                 would report success.
#   plain         any bare "GET this URL" heartbeat, same caveat as betterstack.
#
# `None` means "send nothing", which is a deliberate, meaningful action for the
# providers whose only failure signal is an absent ping.
HEARTBEAT_PROVIDERS: dict[str, Any] = {
    "healthchecks": lambda url, ok: url if ok else url.rstrip("/") + "/fail",
    "cronitor": lambda url, ok: _with_query(url, "state=complete" if ok
                                            else "state=fail"),
    "betterstack": lambda url, ok: url if ok else None,
    "plain": lambda url, ok: url if ok else None,
}

# Healthchecks.io is the default: it is purpose-built for alerting on a ping's
# absence, its free tier covers this project, it has a real failure channel, and
# it can be self-hosted later if depending on a third party becomes a problem.
DEFAULT_HEARTBEAT_PROVIDER = "healthchecks"
HEARTBEAT_PROVIDER_ENV = "CHIRA_HEARTBEAT_PROVIDER"


class Heartbeat:
    """Pings an external monitor. The monitor alerts on the ping's ABSENCE.

    That inversion is the whole design (F12). A collector that emails on failure
    cannot email when the runner never starts, when the workflow is
    auto-disabled after 60 days of repo inactivity, or when the job is silently
    dropped under load. Only a third party expecting a regular ping can notice
    silence.

    **Provider is pluggable, because providers really do differ.** Set
    `CHIRA_HEARTBEAT_PROVIDER` to any key of `HEARTBEAT_PROVIDERS`; the default
    is Healthchecks.io. Switching later is an env var, not a code change. An
    UNKNOWN provider name RAISES rather than falling back to a default: a typo
    that silently pinged the wrong URL shape would leave the check green while
    the collector was dead, which is the one outcome this class exists to
    prevent.

    The URL is a secret supplied by the environment, so it is absent in forks
    and in local dry runs, and that absence is reported rather than ignored.

    **A heartbeat never breaks the run.** Failing to report success is not a
    reason to discard captured data, so every error here is swallowed and
    recorded in `last_error`.
    """

    def __init__(self, url: str | None = None, *, provider: str | None = None,
                 session: Any = None) -> None:
        self.url = url if url is not None else os.environ.get(HEARTBEAT_ENV)
        self.provider = (provider if provider is not None
                         else os.environ.get(HEARTBEAT_PROVIDER_ENV)
                         or DEFAULT_HEARTBEAT_PROVIDER)
        if self.provider not in HEARTBEAT_PROVIDERS:
            raise ValueError(
                f"unknown heartbeat provider {self.provider!r}; expected one of "
                f"{sorted(HEARTBEAT_PROVIDERS)}. Refusing to guess: a wrong URL "
                f"shape leaves the monitor green while the collector is dead"
            )
        self.session = session
        self.pings: list[tuple[str, bool]] = []
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def target(self, *, ok: bool) -> str | None:
        """The URL this provider wants for this outcome, or None to send nothing."""
        if not self.url:
            return None
        return HEARTBEAT_PROVIDERS[self.provider](self.url, ok)

    def ping(self, *, ok: bool = True, detail: str = "") -> bool:
        """Report the run's outcome. Returns whether a ping was delivered.

        The caller reports the return value and must not act on it.
        """
        self.pings.append((detail, ok))
        if not self.configured:
            self.last_error = (f"{HEARTBEAT_ENV} not set; no external monitor to "
                               f"ping (provider {self.provider})")
            return False
        url = self.target(ok=ok)
        if url is None:
            # Correct behaviour, not a failure: for this provider the absence of
            # a ping IS the failure report, so sending one would say "fine".
            self.last_error = (f"provider {self.provider} has no failure channel; "
                               f"stayed silent so the monitor alerts on absence")
            return False
        try:
            sess = self.session
            if sess is None:
                import requests
                sess = requests
            r = sess.get(url, timeout=HEARTBEAT_TIMEOUT)
            code = getattr(r, "status_code", 0)
            if code and 200 <= code < 300:
                return True
            self.last_error = f"heartbeat returned HTTP {code}"
        # Broad by intent: a heartbeat must never raise into the run.
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
        return False


def zero_capture_is_a_failure(captured: int, *, now: datetime | None = None,
                              windows: dict | None = None,
                              targets_due: int | None = None,
                              enumeration_ok: bool = True) -> bool:
    """A zero-capture run fails ONLY when it should have captured something.

    Off-season and outside the poll window, zero is the correct answer and
    failing the workflow would train the reader to ignore red runs, which is
    how a real outage gets missed (T14).

    **`targets_due` matters as much as the window, and leaving it out caused a
    false alarm.** The NHL window opens 2026-09-20 to cover a 2026-09-29
    opener, so there are nine in-season days with no games at all. Season
    active plus window open plus zero captured would have failed every one of
    them and pinged the monitor, which is the alarm-fatigue failure this rule
    exists to avoid.

    **But "no games" and "could not find out" are different**, and only one is
    benign. If enumeration itself failed, the collector does not know whether
    there were games, so that is an outage: `enumeration_ok=False` fails even
    with nothing due. A schedule endpoint returning nothing looks exactly like
    a quiet night otherwise, which is how a silent outage survives a season.
    """
    if captured > 0:
        return False
    if not (is_season_active(now, windows) and in_poll_window(now)):
        return False
    if not enumeration_ok:
        return True
    # A genuinely quiet night: nothing was due, so capturing nothing is right.
    # `targets_due=None` means the caller did not say, and an unknown denominator
    # falls back to the strict rule rather than to silence.
    return targets_due != 0


def session_deadline(started: float | None = None,
                     max_seconds: int = SESSION_MAX_SECONDS) -> float:
    return (started if started is not None else time.monotonic()) + max_seconds


def next_poll_delay(elapsed: float, interval: int = POLL_INTERVAL_SECONDS) -> float:
    """Time until the next poll, never negative.

    Drift-free: the delay is measured from the interval boundary rather than
    from the end of the previous poll, so a slow poll does not push every later
    poll later and shorten the session's coverage.
    """
    return max(0.0, interval - (elapsed % interval))


def describe_plan(now: datetime | None = None, windows: dict | None = None) -> dict:
    """What a run WOULD do, for the pre-season dry run and for the logs."""
    n = et_now(now)
    seasons = active_seasons(now, windows)
    return {
        "et_now": n.isoformat(),
        "utc_now": n.astimezone(UTC).isoformat(),
        "et_offset_hours": n.utcoffset().total_seconds() / 3600,
        "active_seasons": seasons,
        "season_active": bool(seasons),
        "in_poll_window": in_poll_window(now),
        "would_poll": bool(seasons) and in_poll_window(now),
        "minutes_until_window": round(minutes_until_window(now), 1),
        "early_start_minutes": EARLY_START_MINUTES,
        "poll_window_et": f"{POLL_START_ET}-{POLL_END_ET} (spans midnight)",
        "session_max_seconds": SESSION_MAX_SECONDS,
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "heartbeat_configured": Heartbeat().configured,
    }


def upcoming_targets(games: list[dict], *, now: datetime | None = None,
                     lookahead_hours: int = 8,
                     grace_minutes: int = 30) -> list[dict]:
    """Games worth polling right now: tipoff within the lookahead, not long past.

    The grace window keeps a game for a short while after its scheduled tipoff,
    because the tipoff time itself is the thing being re-read and a game that
    started late is still quotable. Games whose start time is unknown are
    KEPT: dropping them would silently exclude exactly the postponed and moved
    games whose timing is most interesting.
    """
    n = et_now(now).astimezone(UTC)
    out = []
    for g in games:
        st = g.get("start_time_utc")
        if st is None:
            out.append(g)
            continue
        if isinstance(st, str):
            st = datetime.fromisoformat(st)
        if st.tzinfo is None:
            raise ValueError(f"naive start_time_utc for {g.get('game_id')}")
        if -timedelta(minutes=grace_minutes) <= st - n <= timedelta(hours=lookahead_hours):
            out.append(g)
    return out


def resolve_targets(client, games: list[dict], abbr_map: dict[str, str],
                    *, bypass_cache: bool = True) -> tuple[list[dict], list[dict]]:
    """Turn upcoming games into pollable targets. Returns (targets, unresolved).

    Reuses the census's own resolver rather than re-deriving slug rules: the
    two date conventions, the per-season abbreviation translations, and the
    away-then-home label check that stops an orientation flip. A flip does not
    crash, it silently swaps which side's price you are recording, so it is
    checked here for exactly the reason the census checks it.

    `bypass_cache` defaults True: a market listed days before the game changes
    between polls, and serving a cached `/events` response would pin the
    collector to the token ids and tipoff of whenever it first looked.
    """
    labels = team_labels(games)
    targets, unresolved = [], []
    for g in games:
        away = abbr_map.get(g["away"], g["away"])
        home = abbr_map.get(g["home"], g["home"])
        try:
            hit = confirm(client, g["sport"], g, away, home, labels,
                          bypass_cache=bypass_cache)
        # Broad by intent: one bad game must not end a session.
        except Exception as e:
            unresolved.append({**g, "reason": f"error:{type(e).__name__}",
                               "detail": str(e)[:200]})
            continue
        market = hit.get("market")
        if not market:
            unresolved.append({
                **g,
                "reason": "no_moneyline_market" if hit.get("rejected_types")
                          else ("label_mismatch_at_slug" if hit.get("saw_events")
                                else "no_market"),
                "detail": ",".join(hit.get("attempted") or []),
            })
            continue
        try:
            tokens = json.loads(market.get("clobTokenIds") or "[]")
        except json.JSONDecodeError:
            tokens = []
        if len(tokens) != 2:
            unresolved.append({**g, "reason": "unparseable_market",
                               "detail": f"{len(tokens)} token ids"})
            continue
        # confirm() validated the outcomes in away-then-home order, so index 0
        # is the away token and index 1 the home token. That ordering is the
        # whole reason confirm is used here instead of a slug lookup.
        targets.append({
            **g,
            "slug": hit.get("slug"),
            "convention": hit.get("convention"),
            "market_question": market.get("question"),
            "gamma_start_time": market.get("gameStartTime"),
            "tokens": [("away", str(tokens[0])), ("home", str(tokens[1]))],
        })
    return targets, unresolved


def poll_target(client, target: dict, *, poll_seq: int, run_id: str,
                now: datetime | None = None) -> list[dict]:
    """Fetch both sides of one market. Returns rows; never raises for one game.

    The tipoff is re-read from the market on every poll (T18): a postponed game
    moves, and a stale target keeps polling a market whose game already started.
    """
    captured = (now or datetime.now(UTC)).astimezone(UTC)
    start = None
    for source in (target.get("start_time_utc"), target.get("gamma_start_time")):
        if isinstance(source, str) and source:
            try:
                start = datetime.fromisoformat(source.replace("Z", "+00:00")
                                               .replace(" ", "T"))
            except ValueError:
                start = None
            if start is not None and start.tzinfo is not None:
                break
            start = None
    rows = []
    for side, token in target["tokens"]:
        try:
            midpoint = client.get_json(midpoint_url(token), bypass_cache=True)
            book = client.get_json(book_url(token), bypass_cache=True)
        # Broad by intent: a dead token must not end the session.
        except Exception:
            continue
        rows.append(quote_row(
            sport=target["sport"], season=target["season"],
            game_id=target["game_id"], slug=target.get("slug"),
            token_id=token, side=side, captured_at=captured,
            midpoint=midpoint, book=book, game_start_time=start,
            poll_seq=poll_seq, run_id=run_id))
    return rows


def complement_check(rows: list[dict]) -> dict:
    """Do the two sides' midpoints still sum to 1? The census's invariant, live.

    Cheap, and it is the one check that catches a token-leg mix-up at capture
    time rather than months later in analysis.
    """
    mids = {r["side"]: r["midpoint"] for r in rows if r.get("midpoint") is not None}
    if len(mids) != 2:
        return {"checked": False, "sum": None}
    total = mids["away"] + mids["home"]
    return {"checked": True, "sum": round(total, 6),
            "ok": abs(total - 1.0) <= COMPLEMENT_LIVE_TOL}
