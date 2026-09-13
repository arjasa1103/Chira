# Chira

Cross-sport market calibration and win-probability engine for NBA and NHL moneylines,
benchmarked against Polymarket closing prices.

Chira asks two questions:

1. **How well does a model built only on public schedule and team data do against a
   real-money market?** The measure is Brier score and log loss on a sealed holdout, plus a
   Clark-West nested test.
2. **Where is the market itself miscalibrated?** It stratifies the market's own calibration
   by liquidity and season phase.

The claim is about calibration, not profit. Nothing here places bets.

> **Project status: week 2 of 11 (September 2026).** The data pipeline is built and
> validated: schedule sources, abbreviation resolution, the census runner, the DuckDB store
> and the validation gate. The full census, the Parquet snapshot, the charts and the model are
> not built yet. See [What exists today](#what-exists-today) before reading further, and
> [PLAN.md](PLAN.md) for the schedule.

---

## Contents

- [What exists today](#what-exists-today)
- [Quick start: your first validated census slice](#quick-start-your-first-validated-census-slice)
- [How-to guides](#how-to-guides)
  - [How to run a full census](#how-to-run-a-full-census)
  - [How to resume an interrupted run](#how-to-resume-an-interrupted-run)
  - [How to re-run the gate without fetching](#how-to-re-run-the-gate-without-fetching)
  - [How to take a clean slice](#how-to-take-a-clean-slice)
  - [How to regenerate the abbreviation maps](#how-to-regenerate-the-abbreviation-maps)
  - [How to cut and verify the snapshot](#how-to-cut-and-verify-the-snapshot)
  - [How to read the snapshot](#how-to-read-the-snapshot)
  - [How to query the census store](#how-to-query-the-census-store)
  - [How to compute calibration metrics](#how-to-compute-calibration-metrics)
  - [How to regenerate the noise floor](#how-to-regenerate-the-noise-floor)
  - [How to re-run the week-1 probes](#how-to-re-run-the-week-1-probes)
  - [How to run the tests and the linter](#how-to-run-the-tests-and-the-linter)
- [Reference](#reference)
  - [Repository layout](#repository-layout)
  - [`run_census.py` command line](#run_censuspy-command-line)
  - [Scripts](#scripts)
  - [Modules](#modules)
  - [Files the pipeline reads and writes](#files-the-pipeline-reads-and-writes)
  - [Store schema](#store-schema)
  - [Miss reasons](#miss-reasons)
  - [Validation gate checks](#validation-gate-checks)
  - [Gate report format](#gate-report-format)
  - [HTTP client behaviour](#http-client-behaviour)
  - [Response cache behaviour](#response-cache-behaviour)
  - [Telemetry events](#telemetry-events)
  - [Key constants](#key-constants)
  - [Dependencies and extras](#dependencies-and-extras)
- [How it works](#how-it-works)
  - [Pipeline](#pipeline)
  - [Design decisions](#design-decisions)
- [Troubleshooting](#troubleshooting)
- [Project documents](#project-documents)
- [Data and terms of use](#data-and-terms-of-use)

---

## What exists today

| Area | Status | Where |
|---|---|---|
| NBA schedule + independent winners (`nba_api`) | Built | `src/chira/schedule.py` |
| NHL schedule + independent winners (`api-web.nhle.com`) | Built | `src/chira/nhl.py` |
| Per-season abbreviation resolution, 124/124 team-seasons | Built | `src/chira/resolve.py`, `scripts/resolve_abbrs.py` |
| Rate-limited HTTP client with backoff and circuit breaker | Built | `src/chira/http.py` |
| Validated on-disk response cache | Built | `src/chira/cache.py` |
| Closing-price extraction (close, T-1h, T-6h, T-24h, staleness, complementarity, raw series) | Built | `src/chira/extract.py` |
| Census runner (resumable, idempotent, re-probes misses) | Built | `src/chira/census.py`, `scripts/run_census.py` |
| DuckDB census store with reconciliation invariants | Built | `src/chira/store.py`, `src/chira/schema.sql` |
| Census validation gate | Built; passes on all four sport-seasons (200-game slices) | `src/chira/gate.py` |
| Calibration metrics and null-distribution simulator | Built | `src/chira/calibration.py` |
| JSONL run telemetry and manifests | Built | `src/chira/telemetry.py` |
| Snapshot writer, verifier and offline reader | Built | `src/chira/snapshot.py`, `scripts/make_snapshot.py` |
| Test suite | 413 tests, offline, ruff-clean | `tests/` |
| Full census of all 5,084 games | **Not run yet** (week 3) | |
| Immutable Parquet snapshot | **Not built** (week 3) | |
| Coverage and calibration charts | **Not built** (week 4) | |
| Feature store, hierarchical model, nested test | **Not built** (weeks 7-9) | |
| Forward price collector | **Not built** (week 4+) | |

Current store state from the week-2 slices: 5,084 games scheduled, 735 priced, 65 misses,
4,284 pending.

---

## Quick start: your first validated census slice

You'll install Chira, build the abbreviation map it needs, pull prices for 200 NBA games
spread across the 2024-25 season, and see the validation gate pass on them. It takes about
10 minutes. Most of that is network time.

### What you'll need

- **macOS or Linux** with network access to `gamma-api.polymarket.com`,
  `clob.polymarket.com`, `api-web.nhle.com` and `stats.nba.com`.
- **[uv](https://docs.astral.sh/uv/)** (tested with 0.9.28). uv installs Python for you.
- **Python 3.12** exactly. `pyproject.toml` pins `>=3.12,<3.13` and `.python-version`
  says `3.12`.
- **A residential or campus IP.** `stats.nba.com` blocks most datacenter and cloud IPs, so
  NBA schedule fetches from CI or a cloud VM usually time out.
- **Disk space.** A 200-game slice caches a few hundred MB. A full census is projected at
  about 3.4 GB of cache (see [TODOS.md](TODOS.md)).

### Step 1: Install

```bash
git clone <your-remote> Chira
cd Chira
uv sync
```

`uv sync` creates `.venv/`, installs the pinned dependencies from `uv.lock`, and installs
`chira` in editable mode, so `import chira` works from any script.

Check it:

```bash
uv run python -c "import chira; print(chira.__version__)"
```

You should see `0.1.0`.

### Step 2: Run the test suite

```bash
uv run pytest
```

Expected: `413 passed`. The suite is offline. Any test that opens a socket fails, so this
passes without a network connection.

### Step 3: Learn the week-1 abbreviation prior

`data/` is gitignored, so a fresh clone has no abbreviation maps. Build the prior first:

```bash
uv run python scripts/learn_abbr.py
```

This pages through closed Polymarket markets in 12 windows per season (about 180 requests)
and writes `data/abbr_map.json`. **A `GAP` line in its coverage summary is expected and fine.**
Gamma's pagination ceiling made it find 0 of 30 NBA teams for 2025-26 when measured. This
file is only a prior: the next step resolves every team from the schedule regardless. Extra
"teams" in 2024-25 are All-Star and 4 Nations exhibition squads, and are ignored too.

### Step 4: Resolve the census abbreviation map

```bash
uv run python scripts/resolve_abbrs.py
```

This is the map the census actually reads. It confirms every schedule abbreviation against
the market's own outcome labels and writes `data/abbr_map_resolved.json`. It took about 40
seconds and 91 probes when measured. Expected end state, for each of the four sport-seasons:

```
2024-25 nhl: 32/32 teams, 19 probes, 1312 games, ...
```

Any `UNRESOLVED:` line means the census will refuse to start for that sport-season. See
[Troubleshooting](#troubleshooting).

### Step 5: Census a 200-game slice

```bash
uv run python scripts/run_census.py --sport nba --season 2024-25 --limit 200
```

What happens, in order:

1. The 2024-25 NBA schedule is fetched from `nba_api` (1,230 games).
2. 200 games are picked evenly across the season (the `stride` strategy).
3. For each game, the runner tries the slug for the ET date, then the next day's date,
   confirms the teams against the market's labels, and pulls the home and away price series.
4. Each game lands in exactly one of `priced` or `misses` in `data/census.duckdb`.
5. Every retryable miss is re-probed once with the cache bypassed.
6. The validation gate runs and writes `data/gate-nba-2024-25.json`.

Progress prints every 25 games. When it finishes you get a report like this (this one is from
the NHL 2025-26 slice):

```
CENSUS GATE nhl 2025-26: PASS
  [ok  ] label_agreement: n_priced=200, by_value={'agree': 200}, disagreements_in_misses=0
  [ok  ] complementarity: checked_ok=200, unchecked_fraction=0.0, unchecked=0, failed=0
  [ok  ] reconciliation: scheduled=1312, priced=200, misses=0, pending=1112, partial_pass=True, double_counted=0, orphans=0
  [ok  ] fault_injection: double_count_caught=True, lost_game_caught=True, store_restored=True, victim=2025020001
  [ok  ] price_discriminates: mean_when_home_won=0.556, mean_when_away_won=0.5144, gap=0.0416, sigma=2.95, n=200
  [ok  ] shuffled_join: true_rate=1.0, shuffled_rate=0.496, shuffled_max=0.56, shuffled_draws=20, chance_rate=0.5024, chance_se=0.0354, shuffled_within_tolerance=True, home_win_rate=0.535
  coverage: 200/200 attempted (1.0), scheduled=1312, pending=1112
  conventions: {'et_plus_1': 11, 'et': 189}
  miss reasons: {}

wrote data/gate-nhl-2025-26.json
```

The process exits `0` when the gate passes and `1` when any check fails.

### Step 6: Look at what you collected

```bash
uv run python -c "
from chira.store import Store
with Store('data/census.duckdb') as s:
    print(s.reconcile('nba', '2024-25'))
    for r in s.priced_rows('nba', '2024-25')[:3]:
        print(r['slug'], r['p_home_close'], r['label_agreement'])
"
```

### What you built

You now have a DuckDB store with 200 priced NBA games, each tied to a slug, a home-side
closing price, T-1h, T-6h and T-24h prices, the raw minute-level price series for both
tokens, a staleness flag, a complementarity check and an independent league winner. You also have a gate report showing the pipeline didn't flip orientation,
lose games, or double-count them. That is exactly the evidence the project requires before
spending the ~16,000 requests of a full census.

Next: [run the full census](#how-to-run-a-full-census), or read
[How it works](#how-it-works) to see why each check exists.

---

## How-to guides

All commands run from the repository root. `uv run python` and `.venv/bin/python` are
interchangeable here.

### How to run a full census

This censuses every game for one sport-season and asserts the full reconciliation identity
`scheduled == priced + misses`.

**Prerequisites:** `data/abbr_map_resolved.json` exists with no unresolved teams, and the
disk has room for the cache.

1. Check free disk space. There is no cache size cap yet (TODOS P1):

   ```bash
   df -h .
   ```

2. Run one sport-season without `--limit`:

   ```bash
   uv run python scripts/run_census.py --sport nba --season 2024-25
   ```

3. Repeat for the other three sport-seasons:

   ```bash
   uv run python scripts/run_census.py --sport nba --season 2025-26
   ```

   ```bash
   uv run python scripts/run_census.py --sport nhl --season 2024-25
   ```

   ```bash
   uv run python scripts/run_census.py --sport nhl --season 2025-26
   ```

Without `--limit` the gate runs with `require_complete=True`, so the reconciliation check
fails unless every scheduled game is settled.

**Cost, measured:** about 16,400 requests for all four, at an achieved 2.42 requests/second
(single-threaded against a 5 rps limit), so roughly 1.9 hours of network time plus the
re-probe pass.

**Verification:** each report shows `reconciliation` passing with `pending=0`, and no
`partial_pass` field.

### How to resume an interrupted run

Run the **exact same command** again. The census skips every game already settled in the
store, so a crash or Ctrl-C loses at most the game in flight.

```bash
uv run python scripts/run_census.py --sport nba --season 2024-25
```

This also applies after a `CircuitOpen` abort (five consecutive failures, or five HTTP 403s).
Wait before resuming: a run of 403s usually means an IP-level block.

Each resume also re-probes **every** accumulated retryable miss with the cache bypassed,
because empty results are never cached. At the projected miss rate that is about 2,000
requests per resume. Pass `--no-reprobe` to skip it, but note that nothing on the miss row
records that the re-probe was skipped.

### How to re-run the gate without fetching

```bash
uv run python scripts/run_census.py --sport nba --season 2024-25 --gate-only
```

No network calls. It re-checks what is already stored and rewrites
`data/gate-<sport>-<season>.json`.

`--gate-only` defaults to the **partial** reconciliation check, because it can't tell a
finished census from a slice. After a full census, add `--complete`:

```bash
uv run python scripts/run_census.py --sport nba --season 2024-25 --gate-only --complete
```

`--gate-only` still opens the store for writing: the fault-injection check corrupts it inside
a transaction and rolls back. Don't run it while a census is writing to the same store.

### How to take a clean slice

`--limit N` takes N games from the **unsettled** games. Running `--limit 200` twice against
one store gives you 400 games, and the second 200 are a stride over whatever the first left
behind. Week 2 lost two slices to exactly this layering (see
[notes/week2-census-gate.md](notes/week2-census-gate.md)).

For a slice you intend to quote numbers from, use a fresh store and log:

```bash
uv run python scripts/run_census.py --sport nhl --season 2024-25 --limit 200 \
  --store data/slice-nhl-2024-25.duckdb --log data/logs/slice-nhl-2024-25.jsonl
```

Keep the default `--cache .http-cache`: the cache is keyed by URL, so a fresh store still
reuses every cached response.

Don't use `--strategy head` for NHL 2024-25. It takes the earliest games in date order, and
Polymarket had no NHL markets before December 2024, so the slice comes back 0 priced and
200 misses.

Every gate report includes `coverage.attempted_by_month`. Compare it against the scheduled
counts to confirm the slice is spread across the season.

### How to regenerate the abbreviation maps

Run both steps whenever `data/` is missing or you suspect a convention change:

```bash
uv run python scripts/learn_abbr.py
```

```bash
uv run python scripts/resolve_abbrs.py
```

`learn_abbr.py` writes the prior `data/abbr_map.json` (`{slug_abbr: nickname}` per sport per
season). `resolve_abbrs.py` reads it and writes `data/abbr_map_resolved.json`
(`{schedule_abbr: slug_abbr}`), the only map the census reads.

The census cache key for slug lookups includes a fingerprint of the resolved map. If a
mapping changes, cached slug lookups are invalidated automatically. Cached price histories
are keyed by token id and survive.

**Verification:** NBA maps are the identity for all 30 teams. NHL needs exactly seven
translations in both seasons:

```
cgy -> cal    mtl -> mon    njd -> nj    sjs -> sj
tbl -> tb     uta -> utah   vgk -> las
```

### How to cut and verify the snapshot

Every phase after the census reads an immutable Parquet snapshot, not the live store. The
snapshot writer refuses an unfinished census.

**Prerequisites:** all four sport-seasons censused in one store with no `--limit`, and no
census process holding the store.

1. Cut it:

   ```bash
   uv run python scripts/make_snapshot.py
   ```

   It checks, for every sport-season in the store, that `scheduled == priced + misses`, that
   no game is in both tables or orphaned, and that every priced game has its raw series. If
   any check fails it prints `REFUSED: ...` and exits `1` without writing anything.

2. Read the output. It prints the snapshot path, the store digest and row counts per table
   and sport-season, after reading the snapshot back and verifying every checksum.

The snapshot lands in `data/snapshots/census-<YYYYMMDD>-<first 12 hex of the store digest>/`:

```
manifest.json               row counts, checksums, digest, git hash, runs, definitions
games/sport=nba/season=2024-25/data_0.parquet
priced/...  misses/...  price_points/...   (each partitioned by sport and season)
runs.parquet
```

Files are written read-only (`0444`) and directories `0555`. Cutting a second snapshot from
an unchanged store fails, because the directory name is the store digest.

**Verification:** re-verify at any time. Silence means every file matches its checksum and no
file was added or removed:

```bash
uv run python -c "from chira.snapshot import verify_snapshot; import sys; verify_snapshot(sys.argv[1])" data/snapshots/<snapshot-id>
```

`data/snapshots/` is gitignored with the rest of `data/`. This is the local input for the
analysis, not a public dataset release (see [Data and terms of use](#data-and-terms-of-use)).

### How to read the snapshot

`open_snapshot` verifies checksums, then returns an in-memory DuckDB connection with one view
per table. It needs no network and no store.

```python
from chira.snapshot import open_snapshot

con = open_snapshot("data/snapshots/<snapshot-id>")
con.execute("""
    SELECT sport, season, count(*) AS priced,
           avg(p_home_close) AS mean_close, avg(p_home_t24h) AS mean_t24h
    FROM priced GROUP BY ALL ORDER BY ALL
""").fetchall()

# One game's raw home-token series, pre- and post-tipoff
con.execute("""
    SELECT t, p FROM price_points
    WHERE sport = 'nba' AND season = '2024-25' AND game_id = '0022400001' AND side = 'home'
    ORDER BY t
""").fetchall()
```

Partition columns `sport` and `season` come back as text. `priced.game_start_time` is text in
the form `2025-01-16T00:30:00+00:00` (UTC) whatever your session timezone.

Read one partition directly if you don't want the whole series table:

```python
import duckdb
duckdb.sql("SELECT count(*) FROM 'data/snapshots/<id>/price_points/sport=nhl/season=2025-26/*.parquet'")
```

### How to query the census store

**From Python, through the `Store` API:**

```python
from chira.store import Store

with Store("data/census.duckdb") as s:
    s.reconcile()                          # all sports and seasons
    s.reconcile("nhl", "2024-25")          # one sport-season
    s.miss_reasons("nhl", "2024-25")       # {'no_market': 64}
    s.label_agreement("nba", "2025-26")    # {'agree': 199}
    rows = s.priced_rows("nba", "2025-26") # list of dicts, one per priced game
    s.points_summary("nba", "2024-25")     # raw series: rows, series, missing, orphaned
    s.digest()                             # content hash over games/priced/misses/price_points
```

**With raw SQL:** open the file directly with `duckdb`. Open it read-only when no census is
running, and pin the timezone so `game_start_time` renders in UTC:

```python
import duckdb

db = duckdb.connect("data/census.duckdb", read_only=True)
db.execute("SET TimeZone='UTC'")
print(db.execute("""
    SELECT sport, season, count(*) AS priced, median(volume) AS median_volume
    FROM priced GROUP BY ALL ORDER BY ALL
""").fetchall())
```

On the week-2 slices that prints median volumes of about $313k (NBA 2024-25), $1.88M
(NBA 2025-26), $58k (NHL 2024-25) and $614k (NHL 2025-26).

Useful queries:

```sql
-- Games attempted but not priced, with every slug that was tried
SELECT game_id, reason, attempted, detail FROM misses
WHERE sport = 'nhl' AND season = '2024-25';

-- Which date convention matched, by month
SELECT strftime(g.et_date, '%Y-%m') AS month, p.convention, count(*)
FROM priced p JOIN games g USING (sport, season, game_id)
GROUP BY ALL ORDER BY ALL;

-- Stale closing prices (flat run of 10+ identical minutes before tipoff)
SELECT sport, season, avg(stale_flat_run::INT) AS stale_share
FROM priced GROUP BY ALL;

-- Which run wrote each row
SELECT run_id, count(*) FROM priced GROUP BY run_id;
```

DuckDB allows one writer per file. A running census holds the lock, so point read-only
analysis at a copy of the file.

### How to compute calibration metrics

Join priced rows to league winners, then call the functions in `chira.calibration`.

```python
import numpy as np
from chira.calibration import brier, cox_slope_intercept, ece, murphy
from chira.store import Store

with Store("data/census.duckdb") as s:
    rows = s.priced_rows("nba", "2025-26")
    winner = dict(s.db.execute(
        "SELECT game_id, winner FROM games WHERE sport='nba' AND season='2025-26'"
    ).fetchall())

p = np.array([r["p_home_close"] for r in rows])
y = np.array([1.0 if winner[r["game_id"]] == "home" else 0.0 for r in rows])

print(len(p), brier(p, y), ece(p, y), cox_slope_intercept(p, y))  # (slope, intercept)
print(murphy(p, y))
```

On the 199-game NBA 2025-26 slice this printed Brier 0.1925, ECE 0.0654 and slope 1.11.
**Don't quote numbers from a slice.** At n near 200 the null noise floor for ECE is around
0.13 at p95 (see [PREREGISTRATION.md](PREREGISTRATION.md) section 4), and the pre-registered
analysis runs on the frozen snapshot, not the live store.

Every metric raises `ValueError` on an empty or length-mismatched sample rather than
returning `nan`. `cox_slope_intercept` also raises if its Newton-Raphson fit doesn't
converge.

### How to regenerate the noise floor

`data/noise_floor.json` is the null distribution the gate thresholds were derived from. No
script in the repo writes it. It comes from `calibration.simulate_null` run over the week-1
price sample, which `scripts/probe_price_distribution.py` writes to `data/price_sample.json`.

```python
import json
import numpy as np
from chira.calibration import simulate_null

pool = np.array([r["p_home_close"] for r in json.load(open("data/price_sample.json"))])
null = {str(n): simulate_null(pool, n=n, reps=1500, seed=0)
        for n in (150, 850, 1230, 2460, 5084)}
json.dump(null, open("data/noise_floor.json", "w"), indent=2)
```

Each entry holds `mean`, `p50`, `p95`, `p99`, `lo2.5` and `hi97.5` for `ece`, `max_bin_dev`,
`slope`, `intercept` and `brier`. If you change the estimator or the gate constants,
`tests/test_week1_facts.py::TestNoiseFloorIsRespected` fails until the two agree again.

### How to re-run the week-1 probes

These are one-off measurements whose conclusions are recorded in `notes/`. Run them only to
re-check a fact.

| Command | Measures | Writes |
|---|---|---|
| `uv run python scripts/probe_rate_limit.py` | Burst ramp 1 to 16 rps against Gamma and CLOB, stops at the first 429 | stdout JSON |
| `uv run python scripts/probe_sustained.py` | 6 rps for 90 s against Gamma, latency drift per 15 s window | stdout |
| `uv run python scripts/probe_price_distribution.py` | 130 random NBA games: closing prices, label agreement, staleness | `data/price_sample.json` |
| `uv run python scripts/probe_nhl_schedule.py` | Shape of the NHL club-schedule, schedule and score endpoints | stdout |

The rate-limit probes send real bursts of up to 16 rps. Don't run them in a loop.

### How to run the tests and the linter

```bash
uv run pytest
```

```bash
uv run pytest --cov=chira
```

```bash
uv run ruff check .
```

The suite has two autouse fixtures in `tests/conftest.py`:

- **No network.** `socket.socket` raises unless a test is marked `@pytest.mark.network`.
  Stub `http.Client` instead. No current test uses the marker and it isn't registered in
  `pyproject.toml`, so add it under `[tool.pytest.ini_options] markers` if you introduce one.
- **UTC.** `TZ=UTC` is set for every test, because a naive timestamp's epoch depends on the
  host timezone.

`tests/test_week1_facts.py` pins verified API facts and the gate thresholds, so a change that
contradicts a recorded measurement fails loudly.

---

## Reference

### Repository layout

```
Chira/
├── README.md                 this file
├── PLAN.md                   eleven-week plan, reviews, decision audit trail
├── PREREGISTRATION.md        analysis commitments made before any model fit
├── TODOS.md                  deferred work with measured justification
├── CLAUDE.md                 agent instructions
├── pyproject.toml            dependencies, extras, ruff and pytest config
├── uv.lock                   pinned dependency lock
├── docs/designs/             approved design document
├── notes/                    week-by-week measurement write-ups
├── scripts/                  runnable entry points (census, resolver, probes)
├── src/chira/                the library
├── tests/                    offline test suite
├── data/                     GITIGNORED: maps, store, gate reports, logs
└── .http-cache/              GITIGNORED: validated response cache
```

### `run_census.py` command line

```
uv run python scripts/run_census.py --sport {nba,nhl} --season SEASON [options]
```

| Flag | Default | Effect |
|---|---|---|
| `--sport {nba,nhl}` | required | Sport to census. |
| `--season SEASON` | required | `2024-25` or `2025-26`. Any other value fails with `KeyError` when the abbreviation map is loaded. |
| `--limit N` | none | Census only N **unsettled** games. Omit for a full pass. |
| `--strategy {stride,head}` | `stride` | How `--limit` picks games. `stride` takes every k-th game across the season; `head` takes the earliest N in date order. |
| `--store PATH` | `data/census.duckdb` | DuckDB store file. Created, with parent directories, if missing. |
| `--cache PATH` | `.http-cache` | Response cache directory. |
| `--log PATH` | `data/logs/census.jsonl` | Telemetry JSONL file. Appended to, never truncated. |
| `--no-reprobe` | off | Skip the cache-bypassed re-probe of retryable misses. |
| `--gate-only` | off | Don't fetch anything; run the gate on the stored rows. |
| `--complete` | off | Require the full-pass identity `scheduled == priced + misses`. Implied by a fetch run without `--limit`; must be passed explicitly with `--gate-only`. |

Fixed paths: the abbreviation map is always read from `data/abbr_map_resolved.json`, and the
gate report is always written to `data/gate-<sport>-<season>.json`, both relative to the
working directory.

**Exit status:** `0` if every gate check passed, `1` if any failed. Uncaught errors
(`CircuitOpen`, `SchemaError`, an unresolved abbreviation map, an NHL schedule short of 1,312
games) exit non-zero with a traceback.

**stdout, in order, for a fetch run:** progress every 25 games, `census:` counts, `reprobe:`
counts, `http:` status counters, `cache:` counters, `cache WRITE FAILURES:` (only if any),
`store digest:`, then the gate report.

### Scripts

| Script | Purpose | Reads | Writes | Network |
|---|---|---|---|---|
| `run_census.py` | Census plus validation gate for one sport-season | `data/abbr_map_resolved.json`, schedules | store, cache, log, gate report | Polymarket, `nba_api` or NHL |
| `make_snapshot.py` | Cut, read back and verify the immutable Parquet snapshot | store | `data/snapshots/<id>/` | none |
| `learn_abbr.py` | Learn the `{slug_abbr: nickname}` prior from Gamma | none | `data/abbr_map.json` | Gamma, ~180 requests |
| `resolve_abbrs.py` | Resolve `{schedule_abbr: slug_abbr}` for both sports and seasons | `data/abbr_map.json` | `data/abbr_map_resolved.json`, cache | Gamma, NHL, `nba_api` |
| `probe_rate_limit.py` | Burst rate-limit ramp | none | stdout | Gamma, CLOB |
| `probe_sustained.py` | Sustained-rate latency check | none | stdout | Gamma |
| `probe_price_distribution.py` | Closing-price sample and early label agreement | none | `data/price_sample.json` | Polymarket, `nba_api` |
| `probe_nhl_schedule.py` | NHL endpoint shape probe | none | stdout | NHL |

### Modules

| Module | Responsibility | Main public names |
|---|---|---|
| `chira.constants` | Verified API facts, season window, gate thresholds, miss-reason enum | `GAMMA`, `CLOB`, `NHL_API`, `USABLE_SEASONS`, `SLUG_DATE_CONVENTIONS`, `MISS_REASONS`, `GATE_*` |
| `chira.http` | Rate-limited JSON client and payload validators | `Client`, `TransientError`, `CircuitOpen`, `SchemaError`, `validate_events`, `validate_prices`, `validate_schedule`, `validate_markets` |
| `chira.cache` | Content-addressed on-disk cache | `Cache`, `fingerprint`, `SCHEMA_VERSION` |
| `chira.schedule` | NBA schedule and slug construction | `nba_games(season)`, `games_from_rows`, `slug_candidates(sport, game, abbr_map)`, `slug` |
| `chira.nhl` | NHL schedule | `nhl_games(client, season)`, `season_code`, `NHL_TEAMS` |
| `chira.abbr` | Week-1 abbreviation learner (prior only) | `learn(client, season)`, `SEASON_SPANS`, `TEAM_COUNT` |
| `chira.resolve` | Schedule-driven abbreviation resolver and slug confirmation | `resolve`, `confirm`, `team_labels`, `invert_learned`, `label_match` |
| `chira.extract` | Closing price, T-1h/T-6h/T-24h looks, raw series, staleness, complementarity, market winner | `closing_price(client, market)`, `label_agreement` |
| `chira.census` | Per-game census, slicing, re-probe, map loading | `run_census`, `census_game`, `reprobe_misses`, `slice_games`, `load_abbr_map`, `tipoff_is_plausible`, `rematch_slugs`, `manifest` |
| `chira.store` | DuckDB store, migrations, reconciliation, raw series, digest | `Store` |
| `chira.snapshot` | Immutable Parquet snapshot: preflight, write, verify, offline read | `create_snapshot`, `verify_snapshot`, `open_snapshot`, `preflight`, `SnapshotError` |
| `chira.gate` | Validation gate checks and report | `run_gate(store, sport, season, require_complete=...)`, `format_report` |
| `chira.calibration` | Metrics and the null simulator | `equal_count_bins`, `ece`, `max_bin_dev`, `cox_slope_intercept`, `brier`, `murphy`, `simulate_null` |
| `chira.telemetry` | JSONL event log and run manifest | `Telemetry`, `run_id`, `git_hash` |

**Game dict shape.** `nba_games` and `nhl_games` both return a list sorted by
`(et_date, game_id)`. Each item has `game_id`, `et_date` (ISO, US-Eastern), `away`, `home`
(lowercase schedule abbreviations), `away_name`, `home_name`, `away_place`, `home_place`,
`away_pts`, `home_pts`, `winner` (`"away"` or `"home"`), and `start_time_utc`, the league's
own UTC tipoff (None if the league source had none). NHL games also carry `neutral_site`. Only completed regular-season games are returned.

### Files the pipeline reads and writes

| Path | Written by | Contents |
|---|---|---|
| `data/abbr_map.json` | `learn_abbr.py` | Per season: `sports.{nba,nhl}` as `{slug_abbr: nickname}`, `conflicts`, `slugs_seen` |
| `data/abbr_map_resolved.json` | `resolve_abbrs.py` | `generated_at`, and `seasons.<season>.<sport>` with `map`, `unresolved`, `probes`, `evidence`, `n_games`, `prior_sizes` |
| `data/census.duckdb` | `run_census.py` | The store (see [Store schema](#store-schema)) |
| `data/gate-<sport>-<season>.json` | `run_census.py` | Gate result (see [Gate report format](#gate-report-format)) |
| `data/snapshots/<id>/` | `make_snapshot.py` | Read-only Parquet snapshot plus `manifest.json` |
| `data/logs/census.jsonl` | `run_census.py` | Telemetry, one JSON object per line |
| `data/price_sample.json` | `probe_price_distribution.py` | Week-1 sample of 128 NBA closing prices |
| `data/noise_floor.json` | `calibration.simulate_null` (by hand) | Null metric distributions at n = 150, 850, 1230, 2460, 5084 |
| `.http-cache/<2 hex>/<sha256>.json` | `Client` via `Cache` | `{url, schema_version, abbr_version, payload}` |

All of `data/` and `.http-cache/` are gitignored. `*.duckdb` must never be committed.

### Store schema

Defined in `src/chira/schema.sql`. Current `SCHEMA_VERSION` is `5`. Existing stores upgrade
through forward-only migrations in `store._MIGRATIONS` when opened.

**`games`**: one row per scheduled game. Key `(sport, season, game_id)`.

| Column | Type | Notes |
|---|---|---|
| `sport`, `season`, `game_id` | TEXT | Key |
| `et_date` | DATE | US-Eastern game date from the schedule |
| `away`, `home` | TEXT | Schedule abbreviations |
| `away_pts`, `home_pts` | INTEGER | Final score |
| `winner` | TEXT | `away` or `home`, from the league, never the market |
| `neutral_site` | BOOLEAN | NHL only; default false |
| `start_time_utc` | TIMESTAMPTZ | The league's own tipoff (NHL `startTimeUTC`, NBA `scheduleleaguev2`); the closing-price cutoff |
| `run_id` | TEXT | Run that last wrote the row |

**`priced`**: one row per game with a usable closing price. Key `(sport, season, game_id)`.

| Column | Type | Notes |
|---|---|---|
| `slug` | TEXT | The Polymarket event slug that matched |
| `convention` | TEXT | `et` or `et_plus_1` |
| `away_nickname`, `home_nickname` | TEXT | Market outcome labels |
| `p_home_close` | DOUBLE | Home token's last price at or before the league's start time (PREREGISTRATION Amendment 1) |
| `p_home_t1h` | DOUBLE | Home token's last price at or before tipoff minus 1 hour; NULL if none |
| `p_home_t6h` | DOUBLE | Same, 6 hours before tipoff; NULL if the market opened later |
| `p_home_t24h` | DOUBLE | Same, 24 hours before tipoff; NULL if the market opened later |
| `n_pre_tipoff` | INTEGER | Home price points before tipoff |
| `secs_before_tip` | INTEGER | Seconds between the last quote and tipoff |
| `stale_flat_run` | BOOLEAN | Last 10 pre-tipoff prices identical |
| `complement_sum` | DOUBLE | `p_home + p_away` at the last simultaneous quote pair before the cutoff, rounded to 6 places; NULL if no away series |
| `complement_ok` | BOOLEAN | True when at least 50% of simultaneous pairs (home quote plus the latest away quote at most 60 s before it, last 2 h) sum to 1 within 1e-6. NULL if no away series or fewer than 10 pairs |
| `complement_share` | DOUBLE | The share behind `complement_ok` |
| `complement_pairs` | INTEGER | Number of simultaneous pairs it was computed from |
| `market_winner` | TEXT | From `outcomePrices` |
| `label_agreement` | TEXT | `agree` (disagreements and unresolved markets go to `misses`) |
| `volume` | DOUBLE | Terminal cumulative market volume |
| `game_start_time` | TIMESTAMPTZ | Polymarket's `gameStartTime`, as reported (can be hours off; see `gamma_delta_min`) |
| `market_type` | TEXT | `sportsMarketType` of the priced market, normally `moneyline` |
| `market_question` | TEXT | The priced market's question, e.g. `Capitals vs. Blue Jackets` |
| `cutoff_source` | TEXT | `league` if the close was cut at the league's start time, `gamma` if it fell back to `gameStartTime` |
| `league_start_time` | TIMESTAMPTZ | The cutoff used, when `cutoff_source = 'league'` |
| `gamma_delta_min` | INTEGER | Gamma's tipoff minus the cutoff, in minutes. Positive means Gamma was late |
| `p_home_close_gamma` | DOUBLE | The close under the original pre-registered definition (cut at `gameStartTime`), kept for audit |
| `run_id` | TEXT | Run that last wrote the row |

**`misses`**: one row per game that couldn't be priced. Key `(sport, season, game_id)`.

| Column | Type | Notes |
|---|---|---|
| `reason` | TEXT | One of [Miss reasons](#miss-reasons); anything else is rejected |
| `attempted` | TEXT | JSON array of every slug tried, sorted. Blocked candidates carry a `[blocked: same-orientation rematch]` suffix |
| `detail` | TEXT | Free text: slug, bad timestamp, complement sum, and so on |
| `run_id` | TEXT | Run that last wrote the row |

**`price_points`**: the raw minute-level series, both tokens, pre- and post-tipoff. No primary
key (it holds tens of millions of rows); append-only per game.

| Column | Type | Notes |
|---|---|---|
| `sport`, `season`, `game_id` | TEXT | The priced game |
| `side` | TEXT | `home` or `away` |
| `t` | BIGINT | Unix seconds |
| `p` | DOUBLE | Price, validated finite and in [0, 1] |
| `run_id` | TEXT | Run that wrote the series |

**`runs`**: `run_id`, `started_at`, `finished_at` (NULL if the run died), `manifest` (JSON).

**`meta`**: key-value pairs; currently only `schema_version`.

**Invariants the store enforces:**

- Writing a `priced` row deletes that game's `misses` row in the same transaction, and the
  reverse. A game is never in both.
- A priced row and its raw series are written in one transaction. Downgrading a priced game
  to a miss deletes its series.
- Re-running writes the same primary keys with `INSERT OR REPLACE`, so rows are never
  duplicated.
- `reconcile()` returns `scheduled`, `priced`, `misses`, `pending` and `balanced`.
  `balanced` only means something once `pending == 0`.
- `digest()` hashes `games`, `priced` and `misses` in canonical order with floats rounded to 9
  places, plus a per-series fingerprint of `price_points` (count, time sum, rounded price
  sum), excluding `runs`. Two runs that collected the same data produce the same digest.
- Every connection sets `TimeZone='UTC'`, so `digest()` doesn't depend on the host.

### Miss reasons

Defined in `constants.MISS_REASONS`. Reasons marked **re-probed** get a second,
cache-bypassed attempt in `reprobe_misses`.

| Reason | Meaning | Re-probed |
|---|---|---|
| `no_market` | Every candidate slug returned an empty event list | yes |
| `label_mismatch_at_slug` | A slug returned events, but none matched both teams in away/home order | yes |
| `no_pre_tipoff_points` | Market exists, home price series has no points before tipoff | yes |
| `unparseable_market` | `clobTokenIds` or `outcomes` malformed, or token ids not numeric | yes |
| `unresolved_market` | Market has no usable `outcomePrices` winner | yes |
| `missing_gameStartTime` | Market has no `gameStartTime` | yes |
| `unparseable_gameStartTime` | `gameStartTime` isn't a timezone-aware ISO timestamp | yes |
| `no_moneyline_market` | The teams matched, but only spread or partial-game markets (no full-game moneyline) | no |
| `implausible_game_start_time` | Fallback only, for a game with no league start time: Gamma's tipoff ET date differs from the schedule, or its ET hour is outside 11-23 | no |
| `postponed_or_split_resolution` | `outcomePrices` is `["0.5","0.5"]` | no |
| `outcome_prices_not_complementary` | `outcomePrices` don't sum to 1 | no |
| `malformed_outcome_prices` | `outcomePrices` isn't a 2-element array | no |
| `complementarity_failed` | Fewer than half of the simultaneous home/away quote pairs in the last 2 h sum to 1 within 1e-6 | no |
| `label_disagreement` | Market winner differs from league winner (E1) | no |

### Validation gate checks

`gate.run_gate` runs seven checks. The gate passes only if all seven pass.

| Check | Passes when | Why it exists |
|---|---|---|
| `label_agreement` | At least one priced row, every priced row is `agree`, and zero `label_disagreement` misses | The only defence against an orientation flip, which mirrors the calibration curve instead of crashing |
| `complementarity` | Zero `complementarity_failed` misses, at least one checked row, and at most 5% of priced rows unchecked (no away series, or too few simultaneous quotes) | Confirms the two outcome tokens are true complements, judged on simultaneous quotes because the two series are sampled independently |
| `reconciliation` | No game in both tables, no orphan rows, `pending >= 0`; plus `pending == 0` when `require_complete` | Protects the coverage denominator |
| `price_series` | Every priced game has a stored raw series and no series belongs to an unpriced game | The snapshot ships the raw series; a gap there would be silent |
| `fault_injection` | Injecting a double count AND deleting a priced row both trip their asserts, and the digest is unchanged after rollback | Proves the reconciliation asserts are actually wired up |
| `price_discriminates` | At least 30 rows, mean `p_home_close` is higher when home won, and the gap is at least 2.0 standard errors | Catches a flipped `clobTokenIds` leg, which label agreement can't see |
| `shuffled_join` | At least 30 rows, home win rate in [0.35, 0.75], true agreement 1.0, and permuted agreement (20 seeded draws) within 5 SE of chance | Measures the chance level and guards the join key. It is **not** independent proof the join is correct; see `gate.py` |

The calibration thresholds `GATE_ECE_MAX`, `GATE_MAX_BIN_DEV`, `GATE_SLOPE_BAND` and
`GATE_INTERCEPT_BAND` are defined in `constants` and pinned by tests, but `run_gate` doesn't
apply them. They are for the full-census integrity analysis in PREREGISTRATION section 4.

### Gate report format

`data/gate-<sport>-<season>.json`:

```
{
  "sport": "nba",
  "season": "2024-25",
  "passed": true,
  "checks": [ {"name": "...", "passed": true, ...check-specific fields}, ... ],
  "coverage": {
    "scheduled": 1230, "priced": 200, "misses": 0, "pending": 1030, "balanced": false,
    "attempted": 200, "coverage_of_attempted": 1.0,
    "conventions": {"et": 200},
    "miss_reasons": {},
    "attempted_by_month": {"2024-10": {"scheduled": 71, "attempted": 12}, ...},
    "cutoff_sources": {"league": 1228},
    "market_types": {"moneyline": 1188, "totals": 40},
    "gamma_tipoff_off_over_1h": 1
  },
  "store_digest": "<sha256>",
  "schema_version": 5,
  "runs": ["census-nba-20260912T115106Z-63345", ...]
}
```

`store_digest` ties the verdict to an exact store state. If you regenerate the store from the
same inputs, the digest should match.

### HTTP client behaviour

`chira.http.Client(rate_rps=5.0, *, cache=None)`

| Behaviour | Value |
|---|---|
| Pacing | One request at a time, at most `rate_rps` per second (default 5.0) |
| User agent | `chira/0.1 (academic research; calibration study)` |
| Timeout | 30 s per request |
| Attempts | `max_attempts=4` per `get_json` call |
| Retried statuses | 429, 403, 502, 503, 504, request exceptions, non-JSON 200s, undecodable JSON |
| Backoff | Starts at 2 s, doubles, capped at 60 s. `Retry-After` is honoured in delta-seconds or HTTP-date form; unparseable values back off 60 s |
| Circuit breaker | Raises `CircuitOpen` after 5 consecutive failures. Every 403 counts immediately, since a WAF 403 is usually an IP block |
| Other non-200 | Raises `RuntimeError` at once and counts toward the circuit |
| Schema change | Validators raise `SchemaError`: valid JSON in the wrong shape stops the run instead of producing fake misses |
| `bypass_cache=True` | Skips the cache read but still writes a fresh valid response |

Endpoint methods: `markets(limit, offset, end_date_min, end_date_max)`,
`event_by_slug(slug)`, `prices_history(token_id, start_ts, fidelity=1)`. `client.stats` is
a `Counter` of `http:<status>`, `cache:hit`, `nonjson200`, `badjson` and exception names.

### Response cache behaviour

`chira.cache.Cache(root, *, abbr_version, schema_version=1)`

- **Only validated payloads are written.** A non-JSON 200 never reaches the cache.
- **Empty results are never cached:** empty event lists, empty price histories, empty
  schedules. An empty answer is ambiguous between "no market" and "upstream hiccup", and it
  must stay re-probeable.
- **Keys:** `sha256("<schema_version>|<abbr_version or ->|<url>")`, sharded two hex characters
  deep. Only slug URLs (containing `slug=`) include the abbreviation-map fingerprint.
- **Cached payloads are re-validated on read**, so a cache written under an old upstream
  schema fails loudly.
- **Atomic writes** via temp file plus `os.replace`. Disk errors increment
  `stats["put_failed"]` and set `last_error` instead of ending the census.
- **Corrupt entries** count as misses.
- **To force a full re-fetch,** delete `.http-cache/`, or bump `cache.SCHEMA_VERSION`.

Measured size: about 0.84 MB per priced game.

### Telemetry events

`data/logs/census.jsonl` gets one flushed JSON line per event. Every line has `ts`, `run_id`
and `kind`.

| `kind` | Fields |
|---|---|
| `run_start` | Manifest: `started_at`, `git_hash`, `cache_schema_version`, `sport`, `season`, `scheduled`, `date_window`, `abbr_map_fingerprint`, `abbr_map_irregulars`, `limit`, `strategy` |
| `census_start` | `scheduled`, `already_settled`, `todo`, `strategy`, `date_span` |
| `rematch_guard` | `blocked_games`: games whose `et_plus_1` slug would bind a next-day rematch |
| `game` | `game_id`, `outcome`; priced adds `slug`, `convention`, `p_home_close`; miss adds `reason`, `attempted`, `detail` |
| `census_end` | `priced`, `miss`, and a count per miss reason |
| `reprobe_recovered` | `game_id`, `slug` |
| `reprobe_end` | `reprobed`, `recovered`, `still_missing`, `not_in_schedule` |
| `run_end` | `counts` per event kind, plus census counts |

Run ids look like `census-nba-20260912T115106Z-63345` (prefix, UTC time, pid).

### Key constants

From `src/chira/constants.py` unless noted.

| Constant | Value | Meaning |
|---|---|---|
| `USABLE_SEASONS` | `("2024-25", "2025-26")` | 2023-24 is excluded: its markets carry almost no volume |
| `SLUG_DATE_CONVENTIONS` | `("et", "et_plus_1")` | Both dates are tried for every game |
| `FIDELITY_MINUTES` | `1` | Price-history resolution |
| `COMPLEMENTARITY_TOL` | `1e-6` | Allowed deviation of `p_home + p_away` from 1 |
| `COMPLEMENT_MAX_GAP_SECONDS` / `COMPLEMENT_MIN_PAIRS` / `COMPLEMENT_MIN_EXACT_SHARE` | `60` / `10` / `0.5` | Simultaneous-quote pairing for the complementarity check, set below the measured minimums (74 pairs, share 0.5755) |
| `STALE_FLAT_RUN` | `10` | Identical trailing minutes that flag a stale close |
| `TIPOFF_ET_HOUR_BAND` | `(11, 23)` | Plausible ET tipoff hours; applied only when a game has no league start time |
| `MONEYLINE_MARKET_TYPE` / `NON_FULL_GAME_MARKET_TYPES` | `"moneyline"` / spreads and first-half types | Market selection by `sportsMarketType` |
| `DEFAULT_LOOKBACK_DAYS` | `7` | Price window start when a market has no `startDate` |
| `HISTORY_PAD_SECONDS` | `3600` | Padding before the price window |
| `GAMMA_LIMIT_CAP` / `GAMMA_OFFSET_CEILING` | `100` / `2100` | Why the census enumerates from schedules, not Gamma |
| `GATE_ECE_MAX` | `0.03` | Full-census ECE ceiling |
| `GATE_MAX_BIN_DEV` | `0.08` | Full-census max per-bin deviation |
| `GATE_SLOPE_BAND` | `(0.93, 1.08)` | Cox slope 95% CI must lie inside |
| `GATE_INTERCEPT_BAND` | `(-0.07, 0.07)` | Cox intercept 95% CI must lie inside |
| `http.RATE_RPS` | `5.0` | Default request rate |
| `http.CIRCUIT_BREAK_AFTER` | `5` | Consecutive failures before abort |
| `gate.MIN_DISCRIMINATION_SIGMA` | `2.0` | Price-discrimination floor |
| `gate.MAX_UNCHECKED_FRACTION` | `0.05` | Complementarity unchecked allowance |
| `nhl.GAMES_PER_SEASON` | `1312` | NHL enumeration must hit this exactly |
| `store.SCHEMA_VERSION` | `5` | Store schema version |
| `cache.SCHEMA_VERSION` | `1` | Cache key version |

### Dependencies and extras

| Group | Packages | Needed for |
|---|---|---|
| default | `requests`, `duckdb`, `numpy`, `scipy`, `nba_api>=1.5,<2` | Everything that exists today |
| `store` extra | `pyarrow`, `matplotlib` | Charts (week 4+; no code uses them yet). The snapshot does **not** need this extra: it is written and read with DuckDB's own Parquet support |
| `model` extra | `numpyro`, `jax` | The hierarchical model (week 8; no code uses them yet) |
| `dev` group | `pytest`, `pytest-cov`, `ruff` | Tests and lint; installed by `uv sync` |

```bash
uv sync --extra store
```

---

## How it works

### Pipeline

```
 nba_api (stats.nba.com)        api-web.nhle.com
        │ nba_games                    │ nhl_games (64 calls)
        └──────────────┬───────────────┘
                       ▼
          schedule: game_id, ET date, away, home, WINNER
                       │
                       │  abbr_map_resolved.json  {schedule_abbr: slug_abbr}
                       ▼
          slug_candidates: nba-<away>-<home>-<ET date>, then <ET date + 1>
                       │
                       ▼
          Gamma /events?slug=   ── confirm both team labels in away/home order,
                       │                 then pick the sportsMarketType=moneyline market
                       ▼
          cutoff = the LEAGUE's start time (Gamma's only as a recorded fallback)
                       │
                       ▼
          CLOB /prices-history  ── home token series, away token series
                       │
                       ▼
          closing_price: close, T-1h, T-6h, T-24h, raw series, staleness,
                         complementarity, market winner
                       │
                       ▼
          label agreement vs league winner
                       │
             ┌─────────┴──────────┐
             ▼                    ▼
          priced               misses (reason + every slug attempted)
             └─────────┬──────────┘
                       ▼
          re-probe retryable misses with cache bypassed
                       │
                       ▼
          validation gate ──► data/gate-<sport>-<season>.json
                       │
                       ▼   (all four sport-seasons complete)
          make_snapshot ──► data/snapshots/<id>/  read-only Parquet + checksums
                       │
                       ▼
          every later phase: open_snapshot(), no network, no store
```

Every HTTP call goes through `Client`: rate limit, backoff, circuit breaker, schema
validation, then the cache.

### Design decisions

**The schedule drives enumeration, not the market.** Gamma's `/markets` endpoint silently
caps `limit` at 100 and returns nothing past offset ~2,100, so you can't list a season by
paginating. The week-1 learner hit this and found 0 of 30 NBA teams for 2025-26. The census
starts from the league schedule, so the denominator is every game that was played, and a
missing market becomes a recorded miss rather than a silent absence.

**Two slug dates per game.** Slugs normally use the US-Eastern game date, but during
October to December 2025 some used the UTC date instead. The switch wasn't simultaneous:
NBA's UTC-dated slugs are in October-November and NHL's in December. Trying only the ET date
would have booked 26 of 960 week-2 games as "no market". The fallback creates its own risk:
for a same-orientation rematch on consecutive days, the `et_plus_1` slug *is* the next
game's slug. `rematch_slugs` blocks those candidates.

**Orientation is verified independently, twice.** A slug says away then home, and
`outcomes`, `outcomePrices` and `clobTokenIds` are index-aligned to that order. A flip
doesn't crash; it mirrors the calibration curve around 0.5 and looks like a finding.
`label_agreement` checks `outcomePrices` against the league's winner. `price_discriminates`
checks the separate `clobTokenIds` leg, which label agreement can't see.

**The closing price is cut at the league's start time, not the market's.** Polymarket's
`gameStartTime` comes from the party being measured, and on the full census it disagreed
with the league by more than 15 minutes on 69 priced games: 24 late (up to 6 hours, which
lets in-game prices into the "close") and 45 early, 36 of them exactly 4 or 5 hours early
(Eastern time recorded as UTC). An earlier ET-hour plausibility rule passed those and
rejected a real 09:00 ET game in Stockholm. This changes the pre-registered definition, so
it is recorded as [PREREGISTRATION.md](PREREGISTRATION.md) Amendment 1, and every priced
row keeps the close under the original definition in `p_home_close_gamma`.

**The moneyline is selected by type, not by being first.** An event holds many markets whose
outcomes are the two team names: the moneyline, spreads, and for NBA 2025-26 a first-half
moneyline. Taking the first label match priced 5 NHL 2025-26 spreads as moneylines. The
census now selects `sportsMarketType == "moneyline"`, accepting an untyped or mistyped market
only when it is the sole label match (40 NBA 2024-25 moneylines are typed `totals` upstream).

**Empty answers are never cached, and misses are re-probed.** An empty `/events` response
means either "no market" or "upstream hiccup", and they look identical. Caching it would turn
a transient failure into a permanent fake miss that still reconciles perfectly. So empties
stay uncached and every retryable miss gets one cache-bypassed second look.

**Every game lands in exactly one table.** The coverage chart that decides the primary sport
is `priced / scheduled`. It goes wrong silently when a game is in neither table or in both.
The store makes both impossible by construction, the gate checks it, and `fault_injection`
proves the check fires.

**Gate thresholds come from simulation, not intuition.** An ECE cap of 0.02 looked
reasonable and would have failed a perfectly calibrated market at every sample size tested.
The adopted thresholds are the simulated null p99 or 95% CI, rounded outward. The same rule
set the price-discrimination floor: an eyeballed 3.0 sigma failed both NHL seasons on correct
data, so it is 2.0, below the 2.73 minimum observed.

**Pre-registration before modelling.** [PREREGISTRATION.md](PREREGISTRATION.md) fixes the
seasons, the closing-price definitions, the metrics, the gate, the model class, the holdout,
the single primary test and the falsification criteria, all before any model is fit. Its git
hash is its timestamp.

**Trade-offs taken.** Single-threaded requests mean a full census takes ~1.9 h instead of
~0.9 h, in exchange for no shared mutable state. There's no cache eviction yet, so a full
census needs ~3.4 GB of free disk. The gate runs on 200-game slices before the full pull, so a
label-agreement failure costs 600 requests instead of 16,000.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `FileNotFoundError: data/abbr_map.json` from `resolve_abbrs.py` | `data/` is gitignored; the prior was never built | Run `uv run python scripts/learn_abbr.py` first |
| `FileNotFoundError: data/abbr_map_resolved.json` from `run_census.py` | Resolved map missing | Run `learn_abbr.py` then `resolve_abbrs.py` |
| `ValueError: <sport> <season> has unresolved teams [...]` | The resolver couldn't confirm a team | Re-run `resolve_abbrs.py`. If it persists, check that team's slugs by hand on Gamma `/events?slug=` and read [notes/week2-abbr-resolution.md](notes/week2-abbr-resolution.md) |
| `KeyError: no resolved abbreviation map for ...` | `--season` isn't `2024-25` or `2025-26`, or the map is incomplete | Use a usable season, or regenerate the map |
| `nba_api` read timeout | `stats.nba.com` is slow or blocks your IP (common on cloud hosts and VPNs) | Retry from a residential network |
| `SchemaError: NHL <season>: enumerated N regular-season games, expected 1312` | One of the 32 club-schedule calls failed or returned a partial payload | Re-run. Don't census a short schedule |
| `SchemaError: /events expected a list ...` | Polymarket changed a response shape | Stop and inspect the endpoint. Don't retry blindly; update the validator and bump `cache.SCHEMA_VERSION` |
| `CircuitOpen: HTTP 403 x5` | Likely an IP-level WAF block | Wait, then resume with the same command |
| `CircuitOpen: 5 consecutive failures` | Upstream outage or network loss | Resume with the same command; completed games are kept |
| `cache WRITE FAILURES: [Errno 28] No space left on device` | Disk full | Free space. The census keeps running uncached but slows down |
| Gate `label_agreement` FAIL with `n_priced=0` | Slice has no priced rows, e.g. `--strategy head` on NHL 2024-25 | Use `--strategy stride` |
| Gate `reconciliation` FAIL after `--gate-only --complete` | The census for that sport-season isn't finished (`pending > 0`) | Finish the census, or drop `--complete` |
| Gate `price_discriminates` FAIL with a negative gap | The token leg is flipped | Treat as a pipeline bug. Inspect `clobTokenIds` ordering for affected slugs |
| Coverage or volume numbers look skewed | Slice layered on an older slice in the same store | Check `attempted_by_month` in the gate report; [take a clean slice](#how-to-take-a-clean-slice) |
| `IO Error: Could not set lock on file` | Another process has the DuckDB file open | Wait for the census to finish, or query a copy |
| `REFUSED: refusing to snapshot an unfinished census` | A sport-season has `pending > 0` | Finish that sport-season's census, then re-run `make_snapshot.py` |
| `REFUSED: ... priced games have no raw series` | A priced row was written without its series (for example by an older schema version) | Re-census those games so row and series are written together |
| `SnapshotError: ... already exists; snapshots are immutable` | The store hasn't changed since the last snapshot | Nothing to do; use the existing snapshot |
| `SnapshotError: N files fail their checksum` | A snapshot file was edited or corrupted | Don't use it. Cut a fresh snapshot from the store |
| `game_start_time` shows a non-UTC offset in your own query | DuckDB renders TIMESTAMPTZ in the session zone | `SET TimeZone='UTC'` on your connection |
| A test fails with `unit tests must not open sockets` | The test reached the real network | Stub `http.Client` in the test |

---

## Project documents

| Document | Read it for |
|---|---|
| [PLAN.md](PLAN.md) | The eleven-week schedule, phase checklists, CEO and engineering reviews, decision audit trail |
| [PREREGISTRATION.md](PREREGISTRATION.md) | Analysis commitments: data, closing price, metrics, gate, model, splits, nested test, strata, risk tiers, falsification |
| [TODOS.md](TODOS.md) | Deferred work with measured costs (cache cap, concurrency, store hardening, sport extensions) |
| [docs/designs/chira-market-calibration-engine.md](docs/designs/chira-market-calibration-engine.md) | The approved design and verified API findings |
| [notes/week1-rate-limit.md](notes/week1-rate-limit.md) | Rate-limit measurements behind the 5 rps setting |
| [notes/week1-slug-conventions.md](notes/week1-slug-conventions.md) | Slug format and the ET/UTC date discovery |
| [notes/week1-tos-check.md](notes/week1-tos-check.md) | Polymarket terms-of-use status (unresolved) |
| [notes/week2-abbr-resolution.md](notes/week2-abbr-resolution.md) | How abbreviations are resolved and regenerated |
| [notes/week2-nhl-schedule.md](notes/week2-nhl-schedule.md) | The NHL schedule source and its verified properties |
| [notes/week2-census-gate.md](notes/week2-census-gate.md) | Gate results, coverage findings, and the contaminated-slice correction |

---

## Data and terms of use

Chira reads public, unauthenticated endpoints: Polymarket Gamma and CLOB, the NHL web API,
and `stats.nba.com` via the community-maintained `nba_api` client.

**Whether Polymarket's terms allow redistributing its price data hasn't been verified**
(see [notes/week1-tos-check.md](notes/week1-tos-check.md)). Until it is:

- keep `data/` and `.http-cache/` out of version control (the `.gitignore` already does),
- share the collector code and derived aggregates, not raw price series,
- let others regenerate the census themselves with the commands in this README.

No license file has been added to the repository yet.
