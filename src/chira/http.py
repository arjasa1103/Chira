"""Rate-limited HTTP client for the Polymarket APIs.

Settings come from the week-1 calibration probe (notes/week1-rate-limit.md):
no 429 was observed at 16 rps burst or 6 rps sustained for 90s, so 5 rps with
3x headroom is the production rate. Backoff is written defensively because a
real 429 was never observed and its Retry-After semantics are unknown.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from collections import Counter
from typing import Any
from urllib.parse import urlencode

import requests

from .constants import CLOB, FIDELITY_MINUTES, GAMMA, GAMMA_LIMIT_CAP

RATE_RPS = 5.0
BACKOFF_START = 2.0
BACKOFF_CAP = 60.0
CIRCUIT_BREAK_AFTER = 5


def _retry_after_seconds(ra: str, fallback: float) -> float:
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
    """Too many consecutive failures. Aborts; NO state is saved.

    Resumability is week-2 work. Until it lands this class only stops the run,
    so the message must not imply a checkpoint exists.
    """


class Client:
    def __init__(self, rate_rps: float = RATE_RPS) -> None:
        if rate_rps <= 0:
            raise ValueError("rate_rps must be positive")
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

    def get_json(self, url: str, *, max_attempts: int = 4) -> Any:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
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
                            return data
                elif r.status_code in (429, 403, 503, 502, 504):
                    ra = r.headers.get("Retry-After")
                    if ra:
                        backoff = _retry_after_seconds(ra, backoff)
                    if r.status_code == 403:
                        # A 403 from a WAF is an IP-level block, not congestion.
                        # Retrying it is how a soft throttle becomes a ban, so
                        # it counts toward the circuit on every occurrence.
                        self._consecutive_failures += 1
                        if self._consecutive_failures >= CIRCUIT_BREAK_AFTER:
                            raise CircuitOpen(
                                f"HTTP 403 x{self._consecutive_failures}: treating as an "
                                f"IP block and aborting. NO state saved."
                            )
                    last = TransientError(f"HTTP {r.status_code} (Retry-After={ra!r})")
                else:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= CIRCUIT_BREAK_AFTER:
                        raise CircuitOpen(
                            f"{self._consecutive_failures} consecutive failures "
                            f"(last HTTP {r.status_code}); aborting. NO state saved."
                        )
                    raise RuntimeError(f"HTTP {r.status_code} for {url}")
            if attempt < max_attempts - 1:
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_CAP)
        self._consecutive_failures += 1
        if self._consecutive_failures >= CIRCUIT_BREAK_AFTER:
            raise CircuitOpen(
                f"{self._consecutive_failures} consecutive failures; aborting. "
                f"NO state saved (resumability is week-2 work). Last: {last}"
            )
        raise last

    def markets(self, *, limit: int = GAMMA_LIMIT_CAP, offset: int = 0,
                end_date_min: str | None = None, end_date_max: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"limit": limit, "offset": offset, "closed": "true"}
        if end_date_min:
            params["end_date_min"] = end_date_min
        if end_date_max:
            params["end_date_max"] = end_date_max
        data = self.get_json(f"{GAMMA}/markets?{urlencode(params)}")
        return data if isinstance(data, list) else []

    def event_by_slug(self, slug: str) -> list[dict]:
        # /markets?slug= returns []; /events?slug= is the working route.
        data = self.get_json(f"{GAMMA}/events?{urlencode({'slug': slug})}")
        return data if isinstance(data, list) else []

    def prices_history(self, token_id: str, start_ts: int,
                       fidelity: int = FIDELITY_MINUTES) -> list[dict]:
        # startTs alone. interval=max with fine fidelity silently returns [] for
        # old markets; startTs+endTs together returns 400 "interval is too long".
        # token_id originates in remote data. An unencoded & or # would silently
        # rewrite the query and the empty result would be recorded as a real miss.
        if not str(token_id).isdigit():
            raise ValueError(f"token_id must be numeric, got {token_id!r}")
        q = urlencode({"market": token_id, "startTs": start_ts, "fidelity": fidelity})
        data = self.get_json(f"{CLOB}/prices-history?{q}")
        return (data or {}).get("history", []) if isinstance(data, dict) else []
