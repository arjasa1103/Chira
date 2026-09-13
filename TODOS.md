# TODOS

Deferred work, with enough context to pick up cold. Sourced from the /autoplan
CEO review (2026-09-11). Items in PLAN.md's task list are NOT duplicated here.

## P1 — Cache sizing before the week-3 full census

**What:** A size cap with oldest-first eviction on `Cache`, plus a preflight
free-space check in `run_census.py` that refuses to start when free space is
below the projected need.

**Why, measured:** `.http-cache` is 786 MB after 2,944 responses — 0.84 MB per
priced game (prices responses average 392 KB, max 3.36 MB). The full 5,084-game
census projects to **~3.4 GB**, and `df` reports 12 GiB free at 95% used.
`Cache.put` no longer raises on a write failure (fixed in the week-2 review), so
ENOSPC now degrades instead of killing the run — but a census that silently
stops caching gets slower and slower with no warning.

**Cheaper alternative, also measured:** trimming cached prices payloads to
[tip-24h, tip] takes the prices cache from ~3.4 GB to ~0.45 GB. Only 10.7% of
points fall in that window, and every value `closing_price` reads comes from the
final hour; `n_pre_tipoff` is already persisted in `priced` so the count
survives trimming. Bump `cache.SCHEMA_VERSION` if you do this.

**Effort:** S (human ~2h / CC ~15min). **Priority:** P1, before week 3.

## P2 — Saturate the rate limit with 2 workers

**What:** Run 2 worker threads against a shared token-bucket limiter.

**Why, measured:** the client achieves **2.42 rps against its configured 5.0** —
`_pace` never sleeps because only one request is ever in flight and median
latency is 0.41s. The full census is therefore ~1.9h instead of ~0.9h. Real
request count also measures ~16,400, not the planned 15,300 (26 games need the
second slug candidate, and misses cost 4 requests each).

**Risk:** shared mutable state is `stats`, `_consecutive_failures`, and the
cache; each needs a lock or a per-worker Session. Not worth it unless the census
has to be re-run more than once.

**Effort:** S (human ~3h / CC ~20min). **Priority:** P2.

## P2 — Store hardening the week-2 review deferred

Four items, all found by the data-migration specialist, all now UNBLOCKED by the
schema migration gate that landed in the review:

1. **`put_games` never prunes.** `scheduled` is the union of every schedule the
   store has ever seen. A game that drops out of the league schedule keeps its
   row, and `reconcile()` still reports balanced. Fix: make `put_games`
   authoritative for its (sport, season) inside one transaction, and log the
   prune count as telemetry rather than cleaning up silently.
2. **No CHECK constraints.** `winner`, `convention`, `label_agreement`, `reason`
   and `p_home_close` are enforced only in Python, and `gate.py` already writes
   raw SQL that bypasses it. DuckDB supports CHECK.
3. **`--gate-only` is a write path.** `check_fault_injection` mutates the live
   store inside a rolled-back transaction, so the store can never be opened
   read-only and the gate cannot run against a frozen artifact. Fix: inject
   against an in-memory copy.
4. **`put_games` is not transactional** (bare `executemany`). Latent today
   because the census re-puts the full list on every resume; it stops being
   latent the moment item 1 lands.

**Effort:** M (human ~5h / CC ~35min). **Priority:** P2, not blocking week 3.

## P2 — Consolidate test fixtures into conftest

**What:** Move `game()`, `priced_row()` and one parameterizable `FakeClient`
into `tests/conftest.py`.

**Why:** `game()` is defined three times and `FakeClient` four, and they have
already drifted twice — `test_extract`'s fake was missing `bypass_cache` and
`test_nhl`'s was missing `validator`, both of which the real `Client` grew in
week 2. A fake that has drifted from the real signature is a test passing
against an interface that no longer exists. Both drifts were caught during the
week-2 review; the third one will not be.

**Effort:** S (human ~2h / CC ~15min). **Priority:** P2.

## P2 — Dataset-release items (feed T11)

- **TIMESTAMPTZ renders in the reader's session zone.** `store.py` pins UTC per
  connection, which protects `digest()`, but that pin is a property of the
  connection and not the file: anyone opening the released census with the
  duckdb CLI or a notebook gets their own machine's zone. Either store
  UTC-normalized `TIMESTAMP` or cast explicitly in the Parquet export, and
  document the convention in the release README.
- **`data/` is a blanket gitignore** and swallows `abbr_map_resolved.json` (a
  census INPUT) and the gate reports (the artifact that decides the primary
  sport). The `.duckdb` file should stay ignored; these two probably should not,
  pending the E18 ToS answer. The gate report now carries `store_digest`, so
  committing it would make "regenerate and compare one hex string" possible.
- **Re-probe re-pays itself on every resume.** `reprobe_misses` re-probes the
  whole accumulated miss set each invocation (~2,034 uncacheable requests,
  ~14 min, at the projected miss rate) because empty results are deliberately
  never cached. Record the re-probe on the miss row so a resume costs nothing.

**Effort:** M. **Priority:** P2.

## P2 — Soccer / tennis / cricket extension

**What:** Extend the census and calibration pipeline to the sports whose Polymarket
coverage was confirmed dense but which sit outside the two-sport scope.

**Why:** Coverage was verified during design probing: a single Jan-2026 window held 116
`nhl-` slugs plus soccer draw markets across `epl`, `elc`, `ere`, `mex`, `spl`, `por`,
`tur`, and cricket under `crind` / `craus`. Soccer especially gives thousands of matches
a season with free xG data from FBref and Understat.

**Pros:** The pipeline is sport-agnostic by design, so marginal cost is an adapter plus an
abbreviation map. More sports strengthen the cross-sport calibration claim, which is the
component with a guaranteed positive result.

**Cons:** Soccer is three-way (draws), so it needs a multinomial scoring path rather than
binary Brier. Cricket and lower-tier soccer markets are thin.

**Context:** Slug convention is `<league>-<away>-<home>-<YYYY-MM-DD>` with a US-Eastern
date, same as NBA/NHL. The abbreviation map must be learned per league per season. Start
from `ingest/abbr.py` once T3 lands.

**Effort:** M (human) → S (with CC). **Priority:** P2.
**Depends on:** PLAN.md T3 (per-season abbreviation map), T7 (snapshot release).

## P2 — Multinomial scoring path for three-way markets

**What:** Generalize `scoring/` from binary Brier/log-loss to the multiclass case.

**Why:** Required by the soccer extension above; soccer draw markets make outcome a
three-way variable. Ranked probability score becomes relevant, though Wheatcroft (2022)
recommends Brier and log loss over RPS even there.

**Pros:** Unlocks the largest-volume sport on Polymarket. Murphy decomposition generalizes.

**Cons:** Calibration curves and edge tiers need rethinking for 3 classes; the
home-side-only convention does not transfer.

**Effort:** M (human) → S (with CC). **Priority:** P2.
**Depends on:** the soccer extension being accepted.

## P3 — In-game / live market analysis

**What:** Analyze how prices move *during* games rather than only pre-tipoff.

**Why:** The minute-level series continues through the game (the probed Grizzlies/Kings
market ran to 06:47 UTC, well past the 02:00 tipoff). That is a full intra-game probability
path, free, already collected by the census.

**Pros:** Zero extra collection cost, it is already in the snapshot. Intra-game win
probability is a well-studied problem with public baselines to compare against.

**Cons:** Different question, different labels, and needs play-by-play joined on game clock.
Would double the project's scope if pulled into the main line.

**Context:** Explicitly out of scope for the calibration project. Revisit only after the
historical half ships.

**Effort:** L (human) → M (with CC). **Priority:** P3.
**Depends on:** T7 (snapshot release) containing full post-tipoff series.

## P3 — Kelly staking / equity-curve simulation

**What:** Translate edge tiers into fractional-Kelly stake sizes and plot an equity curve.

**Why:** It was considered and rejected during design (D6) because it depends on calibration
being proven first, and because it pushes the project toward a staking tool rather than a
measurement instrument.

**Pros:** The most persuasive single chart if, and only if, a real edge is established.

**Cons:** Meaningless before calibration is proven. Invites over-reading a backtest. The
project explicitly contains no bet-placement system and should stay that way.

**Context:** Only revisit if the nested test returns a significant positive result under
both closing-price constructions. If it returns null, this item is dead, not deferred.

**Effort:** S (human) → S (with CC). **Priority:** P3.
**Depends on:** a positive nested-test result.
