"""Rate-limited HTTP client for the Polymarket APIs.

Settings come from the week-1 calibration probe (notes/week1-rate-limit.md):
no 429 was observed at 16 rps burst or 6 rps sustained for 90s, so 5 rps with
3x headroom is the production rate. Backoff is written defensively because a
real 429 was never observed and its Retry-After semantics are unknown.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import requests

from .cache import Cache
from .constants import CLOB, FIDELITY_MINUTES, GAMMA, GAMMA_LIMIT_CAP

RATE_RPS = 5.0
BACKOFF_START = 2.0
BACKOFF_CAP = 60.0
CIRCUIT_BREAK_AFTER = 5


def _retry_after_seconds(ra: str) -> float:
    """Retry-After is either delta-seconds or an HTTP-date (RFC 9110).

    float() rejects the date form; swallowing that left the client retrying on a
    stale 2s backoff against a server that asked for much longer.
    """
    try:
        return min(float(ra), BACKOFF_CAP)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        delta = (parsedate_to_datetime(ra) - datetime.now(UTC)).total_seconds()
        return min(max(delta, 0.0), BACKOFF_CAP)
    except Exception:
        return BACKOFF_CAP  # unparseable: back off maximally, never stay at 2s


class TransientError(RuntimeError):
    """Retryable. Includes non-JSON 200s, which are WAF challenge pages (E6).

    A non-JSON 200 must NEVER be recorded as 'no market exists': that fabricates
    a miss and keeps the census reconciliation assert perfectly balanced while
    the data is silently wrong.
    """


class CircuitOpen(RuntimeError):
    """Too many consecutive failures. Aborts the run.

    The census writes every completed game to the store as it goes and resumes
    from what is already there (see census.py), so an abort here loses at most
    the in-flight game, not the run.
    """


class SchemaError(RuntimeError):
    """The endpoint returned valid JSON in an unexpected SHAPE.

    Deliberately NOT a TransientError and deliberately NOT a miss. A shape
    change means the upstream contract moved, and the correct response is to
    stop the census and look, not to retry 15,000 times or to record 15,000
    fabricated "no market exists" rows.
    """


def validate_events(payload: Any) -> bool:
    """/events?slug= -> list of events. Returns True if the payload is cacheable.

    An empty list is VALID and NOT cacheable: it is the ambiguous case (no
    market vs upstream hiccup), and freezing it into the cache is how a
    transient failure becomes a permanent fabricated miss.
    """
    if not isinstance(payload, list):
        raise SchemaError(f"/events expected a list, got {type(payload).__name__}")
    for ev in payload:
        if not isinstance(ev, dict):
            raise SchemaError(f"/events element is {type(ev).__name__}, not an object")
        markets = ev.get("markets")
        if markets is not None and not isinstance(markets, list):
            raise SchemaError("/events markets is not a list")
    return bool(payload)


def validate_prices(payload: Any) -> bool:
    """/prices-history -> {"history": [{t, p}, ...]}.

    An empty history is a real, stable answer for pre-CLOB markets, but it is
    still not cached: the cost of re-probing a handful of empties is one extra
    request each, and the cost of caching a transient empty is a silent hole in
    the price series.
    """
    if not isinstance(payload, dict):
        raise SchemaError(f"prices-history expected an object, got {type(payload).__name__}")
    history = payload.get("history")
    if not isinstance(history, list):
        raise SchemaError("prices-history has no history list")
    for pt in history:
        if not isinstance(pt, dict):
            raise SchemaError("prices-history point is not an object")
    return bool(history)


def validate_schedule(payload: Any) -> bool:
    """NHL club-schedule-season -> {"games": [...]}.

    This call had NO validator, which meant `cacheable = True` and ANY JSON 200 --
    including `{}` or `{"games": []}` -- was written to the cache permanently. One
    truncated 200 for one team would freeze that team's games out of the census
    DENOMINATOR, where they are invisible: a game never enumerated never becomes a
    row on either side of `scheduled == priced + misses`, so every store guard
    still passes. The whole cache module is built on "an empty result is never
    cached", and this was the one call exempt from it.
    """
    if not isinstance(payload, dict):
        raise SchemaError(f"club-schedule expected an object, got {type(payload).__name__}")
    games = payload.get("games")
    if not isinstance(games, list):
        raise SchemaError("club-schedule has no games list")
    return bool(games)


def validate_markets(payload: Any) -> bool:
    if not isinstance(payload, list):
        raise SchemaError(f"/markets expected a list, got {type(payload).__name__}")
    return bool(payload)


class Client:
    def __init__(self, rate_rps: float = RATE_RPS, *, cache: Cache | None = None) -> None:
        if rate_rps <= 0:
            raise ValueError("rate_rps must be positive")
        self.cache = cache
        self._interval = 1.0 / rate_rps
        self._last = 0.0
        self._consecutive_failures = 0
        self.stats: Counter[str] = Counter()
        self.s = requests.Session()
        self.s.headers["user-agent"] = "chira/0.1 (academic research; calibration study)"
        self.s.headers["accept"] = "application/json"

    def _pace(self) -> None:
        wait = self._interval - (time.perf_counter() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.perf_counter()

    def get_json(self, url: str, *, max_attempts: int = 4,
                 validator: Any = None, bypass_cache: bool = False) -> Any:
        """Fetch and validate. Serves from cache when one is attached.

        The validator runs on CACHED payloads too. A cache written under an
        older upstream schema is exactly as wrong as a fresh bad response, and
        it is worse for being invisible.

        `bypass_cache` ignores an existing entry but still writes the fresh one:
        the E6 re-probe exists to distinguish a real miss from a transient one,
        and a recovered market should be cached for the next run.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.cache is not None and not bypass_cache:
            hit = self.cache.get(url)
            if hit is not None:
                if validator is not None:
                    validator(hit)
                self.stats["cache:hit"] += 1
                return hit
        last: Exception = TransientError("no attempts made")
        backoff = BACKOFF_START
        for attempt in range(max_attempts):
            self._pace()
            try:
                r = self.s.get(url, timeout=30)
            except requests.RequestException as e:
                self.stats[f"exc:{type(e).__name__}"] += 1
                last = TransientError(str(e))
            else:
                self.stats[f"http:{r.status_code}"] += 1
                if r.status_code == 200:
                    ctype = r.headers.get("content-type", "")
                    if "json" not in ctype.lower():
                        # WAF challenge page or interstitial. Transient, never a miss.
                        self.stats["nonjson200"] += 1
                        last = TransientError(f"HTTP 200 with content-type {ctype!r}")
                    else:
                        try:
                            data = r.json()
                        except json.JSONDecodeError as e:
                            self.stats["badjson"] += 1
                            last = TransientError(f"200 but undecodable JSON: {e}")
                        else:
                            self._consecutive_failures = 0
                            cacheable = True
                            if validator is not None:
                                cacheable = validator(data)
                            # bypass_cache skips the READ, not the write. A
                            # re-probe that recovers a market should leave it
                            # cached for the next run.
                            if cacheable and self.cache is not None:
                                self.cache.put(url, data)
                            return data
                elif r.status_code in (429, 403, 503, 502, 504):
                    ra = r.headers.get("Retry-After")
                    if ra:
                        backoff = _retry_after_seconds(ra)
                    if r.status_code == 403:
                        # A 403 from a WAF is an IP-level block, not congestion.
                        # Retrying it is how a soft throttle becomes a ban, so
                        # it counts toward the circuit on every occurrence.
                        self._consecutive_failures += 1
                        if self._consecutive_failures >= CIRCUIT_BREAK_AFTER:
                            raise CircuitOpen(
                                f"HTTP 403 x{self._consecutive_failures}: treating as an "
                                f"IP block and aborting. Resume from the store, which "
                                f"holds every completed game."
                            )
                    last = TransientError(f"HTTP {r.status_code} (Retry-After={ra!r})")
                else:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= CIRCUIT_BREAK_AFTER:
                        raise CircuitOpen(
                            f"{self._consecutive_failures} consecutive failures "
                            f"(last HTTP {r.status_code}); aborting. Resume from the "
                            f"store, which holds every completed game."
                        )
                    raise RuntimeError(f"HTTP {r.status_code} for {url}")
            if attempt < max_attempts - 1:
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_CAP)
        self._consecutive_failures += 1
        if self._consecutive_failures >= CIRCUIT_BREAK_AFTER:
            raise CircuitOpen(
                f"{self._consecutive_failures} consecutive failures; aborting. "
                f"Resume from the store, which holds every completed game. Last: {last}"
            )
        raise last

    def markets(self, *, limit: int = GAMMA_LIMIT_CAP, offset: int = 0,
                end_date_min: str | None = None, end_date_max: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"limit": limit, "offset": offset, "closed": "true"}
        if end_date_min:
            params["end_date_min"] = end_date_min
        if end_date_max:
            params["end_date_max"] = end_date_max
        data = self.get_json(f"{GAMMA}/markets?{urlencode(params)}",
                             validator=validate_markets)
        return data if isinstance(data, list) else []

    def event_by_slug(self, slug: str, *, bypass_cache: bool = False) -> list[dict]:
        # /markets?slug= returns []; /events?slug= is the working route.
        data = self.get_json(f"{GAMMA}/events?{urlencode({'slug': slug})}",
                             validator=validate_events, bypass_cache=bypass_cache)
        return data if isinstance(data, list) else []

    def prices_history(self, token_id: str, start_ts: int,
                       fidelity: int = FIDELITY_MINUTES, *,
                       bypass_cache: bool = False) -> list[dict]:
        # startTs alone. interval=max with fine fidelity silently returns [] for
        # old markets; startTs+endTs together returns 400 "interval is too long".
        # token_id originates in remote data. An unencoded & or # would silently
        # rewrite the query and the empty result would be recorded as a real miss.
        # isascii() as well as isdigit(): '١٢٣'.isdigit() and '²'.isdigit() are both
        # True, so isdigit alone admits ids that can never be valid and turns a loud
        # ValueError into an ordinary empty-history miss.
        tok = str(token_id)
        if not (tok.isascii() and tok.isdigit()):
            raise ValueError(f"token_id must be ASCII digits, got {token_id!r}")
        q = urlencode({"market": token_id, "startTs": start_ts, "fidelity": fidelity})
        data = self.get_json(f"{CLOB}/prices-history?{q}",
                             validator=validate_prices, bypass_cache=bypass_cache)
        return (data or {}).get("history", []) if isinstance(data, dict) else []
