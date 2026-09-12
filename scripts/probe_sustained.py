"""E14b — sustained-rate probe.

A 5-second burst does not test a 15,300-request census. This runs a moderate
sustained rate for long enough to expose a wider-window quota (per-minute or
per-hour token bucket) and to check whether latency degrades under steady load.
"""

from __future__ import annotations

import statistics
import time

import requests

URL = "https://gamma-api.polymarket.com/markets?limit=1&closed=true"
RATE = 6          # requests/sec, a plausible production rate with headroom
DURATION = 90     # seconds
BUCKET = 15       # report per 15s window


def main() -> None:
    s = requests.Session()
    s.headers["user-agent"] = "chira-research-probe/0.1 (sustained calibration)"
    interval = 1.0 / RATE
    t_start = time.perf_counter()
    lat: list[tuple[float, float, int]] = []  # (elapsed, ms, status)
    i = 0
    while time.perf_counter() - t_start < DURATION:
        t0 = time.perf_counter()
        try:
            code = s.get(URL, timeout=20, headers={"accept": "application/json"}).status_code
        except requests.RequestException:
            code = -1
        dt = (time.perf_counter() - t0) * 1000
        lat.append((t0 - t_start, dt, code))
        if code == 429:
            print(f"  429 at request {i} ({t0 - t_start:.1f}s in) -> STOPPING")
            break
        i += 1
        sleep = interval - (time.perf_counter() - t0)
        if sleep > 0:
            time.sleep(sleep)

    print(f"\nsent {len(lat)} requests over {lat[-1][0]:.1f}s "
          f"(target {RATE} rps, actual {len(lat)/lat[-1][0]:.1f} rps)")
    print(f"status counts: ", end="")
    counts: dict[int, int] = {}
    for _, _, c in lat:
        counts[c] = counts.get(c, 0) + 1
    print(counts)

    print(f"\n{'window':>10}  {'n':>4}  {'p50ms':>7}  {'p95ms':>7}  {'max':>7}  non-200")
    for w in range(0, int(DURATION), BUCKET):
        chunk = [(m, c) for e, m, c in lat if w <= e < w + BUCKET]
        if not chunk:
            continue
        ms = [m for m, _ in chunk]
        bad = sum(1 for _, c in chunk if c != 200)
        print(f"{w:>4}-{w+BUCKET:<5}  {len(chunk):>4}  {statistics.median(ms):>7.1f}  "
              f"{sorted(ms)[int(len(ms)*0.95)-1]:>7.1f}  {max(ms):>7.1f}  {bad:>7}")

    first = [m for e, m, _ in lat if e < 15]
    last = [m for e, m, _ in lat if e >= DURATION - 15]
    if first and last:
        drift = statistics.median(last) - statistics.median(first)
        print(f"\nlatency drift first15s -> last15s: {drift:+.1f}ms "
              f"({'degrading' if drift > 30 else 'stable'})")
    all429 = counts.get(429, 0)
    print(f"\nVERDICT: {'RATE LIMITED' if all429 else 'NO rate limit hit'} "
          f"at {RATE} rps sustained for {DURATION}s ({len(lat)} requests)")


if __name__ == "__main__":
    main()
