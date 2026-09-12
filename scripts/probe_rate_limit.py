"""E14 — rate-limit calibration probe.

Ramps request rate against each host until the first 429, then stops. Records
status codes, latency percentiles, any Retry-After header, and recovery time.

Deliberately conservative: aborts the whole ramp on the first 429, caps total
requests per host, and never runs concurrent requests. The point is to learn
the ceiling cheaply, not to find it by force.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass

import requests

GAMMA_URL = "https://gamma-api.polymarket.com/markets?limit=1&closed=true"
CLOB_URL = (
    "https://clob.polymarket.com/prices-history"
    "?market=41257670817876317355997233596113195194194608207987371129645019730826567930842"
    "&interval=max&fidelity=1440"
)

# Burst rates to try, requests per second. Stop at the first 429.
RATES = [1, 2, 4, 8, 16]
BURST_SECONDS = 5
MAX_REQUESTS_PER_HOST = 200


@dataclass
class RateResult:
    rate_rps: int
    sent: int
    ok: int
    rate_limited: int
    other_errors: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    retry_after: str | None
    status_counts: dict


def burst(url: str, rate: int, seconds: int, session: requests.Session) -> RateResult:
    interval = 1.0 / rate
    lat: list[float] = []
    counts: dict[str, int] = {}
    ok = limited = other = 0
    retry_after = None
    n = int(rate * seconds)
    for i in range(n):
        t0 = time.perf_counter()
        try:
            r = session.get(url, timeout=20, headers={"accept": "application/json"})
            code = r.status_code
        except requests.RequestException as e:
            code = f"EXC:{type(e).__name__}"
            r = None
        dt = (time.perf_counter() - t0) * 1000
        lat.append(dt)
        key = str(code)
        counts[key] = counts.get(key, 0) + 1
        if code == 200:
            ok += 1
        elif code == 429:
            limited += 1
            if r is not None:
                retry_after = r.headers.get("Retry-After") or r.headers.get("retry-after")
            break
        else:
            other += 1
        # pace to the target rate
        sleep = interval - (time.perf_counter() - t0)
        if sleep > 0 and i < n - 1:
            time.sleep(sleep)
    return RateResult(
        rate_rps=rate,
        sent=len(lat),
        ok=ok,
        rate_limited=limited,
        other_errors=other,
        p50_ms=round(statistics.median(lat), 1) if lat else 0.0,
        p95_ms=round(sorted(lat)[int(len(lat) * 0.95) - 1], 1) if len(lat) >= 2 else 0.0,
        max_ms=round(max(lat), 1) if lat else 0.0,
        retry_after=retry_after,
        status_counts=counts,
    )


def measure_recovery(url: str, session: requests.Session, max_wait: int = 70) -> float | None:
    """After a 429, poll once per second until a 200 comes back."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < max_wait:
        time.sleep(1.0)
        try:
            if session.get(url, timeout=20, headers={"accept": "application/json"}).status_code == 200:
                return round(time.perf_counter() - t0, 1)
        except requests.RequestException:
            pass
    return None


def probe(name: str, url: str) -> dict:
    session = requests.Session()
    session.headers["user-agent"] = "chira-research-probe/0.1 (rate-limit calibration)"
    results: list[RateResult] = []
    total = 0
    hit_limit = False
    recovery = None
    for rate in RATES:
        if total >= MAX_REQUESTS_PER_HOST:
            break
        res = burst(url, rate, BURST_SECONDS, session)
        total += res.sent
        results.append(res)
        print(
            f"  {name:6} {rate:3d} rps -> sent={res.sent:3d} ok={res.ok:3d} "
            f"429={res.rate_limited} other={res.other_errors} "
            f"p50={res.p50_ms:7.1f}ms p95={res.p95_ms:7.1f}ms {res.status_counts}",
            flush=True,
        )
        if res.rate_limited:
            hit_limit = True
            print(f"  {name:6} 429 at {rate} rps. Retry-After={res.retry_after!r}. Measuring recovery...", flush=True)
            recovery = measure_recovery(url, session)
            print(f"  {name:6} recovered after {recovery}s", flush=True)
            break
        if res.other_errors:
            break
        time.sleep(2.0)  # cool off between rungs
    return {
        "host": name,
        "url": url,
        "hit_rate_limit": hit_limit,
        "max_rate_tested_rps": results[-1].rate_rps if results else None,
        "retry_after_header": recovery is not None and results[-1].retry_after or (results[-1].retry_after if results else None),
        "recovery_seconds": recovery,
        "total_requests": total,
        "rungs": [asdict(r) for r in results],
    }


def main() -> int:
    out = {"probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "hosts": []}
    for name, url in (("gamma", GAMMA_URL), ("clob", CLOB_URL)):
        print(f"--- {name} ---", flush=True)
        out["hosts"].append(probe(name, url))
        time.sleep(3.0)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
