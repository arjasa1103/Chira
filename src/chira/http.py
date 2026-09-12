"""Rate-limited HTTP client for the Polymarket APIs.

Settings come from the week-1 calibration probe (notes/week1-rate-limit.md):
no 429 was observed at 16 rps burst or 6 rps sustained for 90s, so 5 rps with
3x headroom is the production rate. Backoff is written defensively because a
real 429 was never observed and its Retry-After semantics are unknown.
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from .constants import CLOB, GAMMA

RATE_RPS = 5.0
BACKOFF_START = 2.0
BACKOFF_CAP = 60.0
CIRCUIT_BREAK_AFTER = 5


class TransientError(RuntimeError):
    """Retryable. Includes non-JSON 200s, which are WAF challenge pages (E6).

    A non-JSON 200 must NEVER be recorded as 'no market exists': that fabricates
    a miss and keeps the census reconciliation assert perfectly balanced while
    the data is silently wrong.
    """


class CircuitOpen(RuntimeError):
    """Too many consecutive failures. Park and exit rather than grind unattended."""


class Client:
    def __init__(self, rate_rps: float = RATE_RPS) -> None:
        self._interval = 1.0 / rate_rps
        self._last = 0.0
        self._consecutive_failures = 0
        self.stats: dict[str, int] = {}
        self.s = requests.Session()
        self.s.headers["user-agent"] = "chira/0.1 (academic research; calibration study)"
        self.s.headers["accept"] = "application/json"

    def _pace(self) -> None:
        wait = self._interval - (time.perf_counter() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.perf_counter()

    def _bump(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    def get_json(self, url: str, *, max_attempts: int = 4) -> Any:
        backoff = BACKOFF_START
        for attempt in range(max_attempts):
            self._pace()
            try:
                r = self.s.get(url, timeout=30)
            except requests.RequestException as e:
                self._bump(f"exc:{type(e).__name__}")
                last = TransientError(str(e))
            else:
                self._bump(f"http:{r.status_code}")
                if r.status_code == 200:
                    ctype = r.headers.get("content-type", "")
                    if "json" not in ctype.lower():
                        # WAF challenge page or interstitial. Transient, never a miss.
                        self._bump("nonjson200")
                        last = TransientError(f"HTTP 200 with content-type {ctype!r}")
                    else:
                        try:
                            data = r.json()
                        except json.JSONDecodeError as e:
                            self._bump("badjson")
                            last = TransientError(f"200 but undecodable JSON: {e}")
                        else:
                            self._consecutive_failures = 0
                            return data
                elif r.status_code in (429, 403, 503, 502, 504):
                    ra = r.headers.get("Retry-After")
                    if ra:
                        try:
                            backoff = min(float(ra), BACKOFF_CAP)
                        except ValueError:
                            pass
                    last = TransientError(f"HTTP {r.status_code} (Retry-After={ra!r})")
                else:
                    self._consecutive_failures += 1
                    raise RuntimeError(f"HTTP {r.status_code} for {url}")
            if attempt < max_attempts - 1:
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_CAP)
        self._consecutive_failures += 1
        if self._consecutive_failures >= CIRCUIT_BREAK_AFTER:
            raise CircuitOpen(
                f"{self._consecutive_failures} consecutive failures; parking. Last: {last}"
            )
        raise last

    def markets(self, *, limit: int = 100, offset: int = 0, closed: bool = True,
                end_date_min: str | None = None, end_date_max: str | None = None) -> list[dict]:
        q = [f"limit={limit}", f"offset={offset}", f"closed={'true' if closed else 'false'}"]
        if end_date_min:
            q.append(f"end_date_min={end_date_min}")
        if end_date_max:
            q.append(f"end_date_max={end_date_max}")
        data = self.get_json(f"{GAMMA}/markets?" + "&".join(q))
        return data if isinstance(data, list) else []

    def event_by_slug(self, slug: str) -> list[dict]:
        # /markets?slug= returns []; /events?slug= is the working route.
        data = self.get_json(f"{GAMMA}/events?slug={slug}")
        return data if isinstance(data, list) else []

    def prices_history(self, token_id: str, start_ts: int, fidelity: int = 1) -> list[dict]:
        # startTs alone. interval=max with fine fidelity silently returns [] for
        # old markets; startTs+endTs together returns 400 "interval is too long".
        data = self.get_json(
            f"{CLOB}/prices-history?market={token_id}&startTs={start_ts}&fidelity={fidelity}"
        )
        return (data or {}).get("history", []) if isinstance(data, dict) else []
