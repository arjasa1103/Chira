# E14 — rate-limit calibration (week 1)

**Status: DONE. No rate limit found. The census is not schedule-limited.**

## Measured

Burst ramp (`scripts/probe_rate_limit.py`), 1 → 16 rps in 5s bursts, both hosts:

| Host | 1 rps | 2 rps | 4 rps | 8 rps | 16 rps | 429s |
|---|---|---|---|---|---|---|
| gamma | 5/5 ok | 10/10 | 20/20 | 40/40 | 80/80 | **0** |
| clob | 5/5 ok | 10/10 | 20/20 | 40/40 | 80/80 | **0** |

p50 latency 41-62ms on both, p95 under 155ms. 155 requests per host, all 200.

Sustained (`scripts/probe_sustained.py`), gamma, 6 rps for 90s:

- **527 requests, 100% HTTP 200, zero 429.**
- p50 stable across six 15s windows (39-45ms); latency drift first-15s to last-15s
  **+3.1ms**, i.e. no degradation under steady load.
- No per-minute token-bucket exhaustion visible at this volume.

## Schedule consequence

The census is ~15,300 requests.

| Rate | Census wall-clock |
|---|---|
| 6 rps (measured safe) | **~42 min** |
| 5 rps (recommended production) | **~51 min** |
| 4 rps (very conservative) | ~64 min |

**The eng re-review estimated 4-13 hours at 1-3 rps. The real figure is under an hour.**
Census wall-clock is removed as a schedule risk. Week 3 has far more slack than assumed.

## What was NOT established (do not over-read this)

1. **Volume ceiling.** 527 sustained requests is not 15,300. A per-hour or per-day quota
   could still exist above the tested volume. The circuit breaker is still required.
2. **Expensive-query behaviour.** The sustained test hit `gamma /markets?limit=1`, a tiny
   response. `prices-history` at `fidelity=1` returns ~9,300 points per call and is far more
   expensive server-side; it may be throttled differently. The burst test covered it only to
   16 rps for 5s.
3. **429 semantics are unknown.** No 429 was ever triggered, so `Retry-After` format and
   recovery time were never observed. Backoff code must therefore be written defensively and
   **cannot be tested against a real 429** until one occurs in the wild.

## Production settings adopted

- **5 rps sustained**, single-threaded, no concurrency. Leaves 3x headroom under the
  measured-safe rate and finishes the census in under an hour.
- Exponential backoff on 429/403/503, starting at 2s, capped at 60s.
- **Circuit breaker:** after 5 consecutive failures, park the remaining slugs to the resume
  file and exit non-zero rather than backing off for hours unattended.
- Treat any non-JSON 200 as a transient error, never as a miss (E6).
