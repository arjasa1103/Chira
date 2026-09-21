# TODOS

Deferred work, with enough context to pick up cold. Sourced from the /autoplan
CEO review (2026-09-11). Items in PLAN.md's task list are NOT duplicated here.

## RESOLVED 2026-09-20 — The pre-registered 2x2 is not orthogonal

**Decision: cut volume levels WITHIN season phase.** Recorded as PREREGISTRATION.md
Amendment 3a, with the measured confound (Spearman +0.36 to +0.53; 66-72% of low-liquidity
games early) and the restored balance (0.503-0.534, cells 221-312). The residualized
alternative was tested and rejected: comparable orthogonality, but it buries a fitted model
in a pre-registered definition.

**Implementation left for week 5:** the strata builder cuts volume inside each phase, and
the per-cell n check uses the per-n null rows in `CENSUS_NULL_ECE_P99_BY_N`, never the
pooled cap.

**Original item, kept for the record:**

**What:** Re-examine the section-8 strata design before building headline 2.

**Why, measured in week 4 (chart 1):** median volume climbs steeply WITHIN each season —
NBA 2024-25 goes ~$50k in week 1 to ~$400k by week 18, and every other sport-season shows
the same shape. PREREGISTRATION.md section 8 cuts liquidity on **within-season** volume
deciles precisely so that "low liquidity" does not just mean "2024-25". That defends against
the BETWEEN-season confound and does nothing about the within-season one: a low volume decile
is disproportionately an early-season game, so liquidity and season phase — the two axes of
the pre-registered 2x2 — are correlated by construction.

**Options, none chosen:** cut volume deciles *within season phase* rather than within season;
or residualize volume on week-of-season and stratify on the residual; or keep the 2x2 and
report the correlation as a stated limitation. The first two change a pre-registered
definition and would need an amendment; the third is honest but weakens the primary test.

**Do not skip:** the section-8 primary directional test is the slope difference BETWEEN
strata, so a confound between the two axes lands directly on the headline.

**Effort:** S to decide (human ~2h / CC ~20min), M if it needs an amendment. **Priority:** P1.

## RESOLVED 2026-09-21 — 318 priced games carry no volume

**Amendment 3c's proxy was WITHDRAWN on measurement (Amendment 4).** Event-level volume is
present on only ~36% of the affected games and reads $350-$11,169 against season medians of
$604k and $2.03M, so it is neither the same quantity nor an upper bound. The 318 games are
excluded from the liquidity axis as a named, counted category and never proxied; they stay
in the phase axis and in every unstratified number.

**8 of the 326 were never missing volume:** their moneyline market carries `volumeClob`,
which `census._volume` did not try. Measured equal to the stored volume (ratio 1.000) on 7
normal games, so it recovers the pre-registered quantity. `_volume` now tries it last, and
the recovered values live in `data/volume_patch/` with a checksum manifest naming the base
snapshot digest -- the frozen snapshot is untouched. All 326 resolved from the week-3 cache,
so they are census-time values.

**Nothing left to do here.** The remaining cost is stated in Amendment 4: NBA 2025-26's late
cells hold 212 games against 321 early.

**Original item, kept for the record:**

**Cause confirmed** against the live API on 2026-09-19, no longer inferred: for games in the
2026-03-04..25 window the Gamma market object carries no volume field at all, while a 2025
market carries nine. 161 of 170 NBA and 157 of 167 NHL priced games in that window are hit,
so it is upstream and calendar-shaped, not a sport's code path.

**Decision: use event-level volume as a flagged proxy** where the market has none, per
PREREGISTRATION.md Amendment 3c. Sampled 24 affected games: 15 have event-level volume, 9
have nothing. Games with neither stay out of the liquidity strata as a counted, named
category.

**Implementation left for week 5, and it is not trivial:**
1. Fetch event-level volume for the 318 games (~318 requests) and store it as a NEW column
   (`volume_event`) plus `volume_source`, never overwriting `volume`. The frozen snapshot's
   content hash covers the pre-registered definition and must keep covering it.
2. That means a re-cut snapshot or a documented side table. Decide which before fetching;
   a second snapshot needs disk headroom this machine does not currently have (3.9 GB free).
3. Event volume sums every market type in the event, so it is an upper bound. The mandatory
   sensitivity re-run with all proxied games excluded is part of the analysis, not optional.

**Original item, kept for the record:**

**What:** Establish why Gamma returned no volume field, and decide how headline 2 treats them.

**Why, measured in week 4:** `volume IS NULL` on 318 priced games — 161 NBA and 157 NHL, all
between **2026-03-04 and 2026-03-25**, plus 8 NBA games on 2024-11-12/13. Both sports breaking
in the same three-week window points upstream rather than at one sport's code path, but that
was inferred, not confirmed against the API.

**Why it is not cosmetic:** that is 13% of the 2025-26 season, and it is a contiguous calendar
block. Dropping those games from a liquidity stratum would delete a specific slice of the
season and re-introduce the season-phase confound by the back door — see the P1 item above.
Charts currently report `volume_missing` beside every median rather than dropping anything.

**Note:** the volume definition is frozen in the snapshot manifest with a content hash, so
re-fetching volume now would produce a value the pre-registration does not describe. Any fix
is "record the gap", not "backfill it".

**Effort:** S (human ~2h / CC ~15min). **Priority:** P2.

## RESOLVED 2026-09-20 — NHL's market is nearly uninformative

**Decision: NHL is a contrast case, not the primary sample.** The headline-2 primary
directional test is computed on NBA; NHL is reported in full as the case where a market is
perfectly calibrated and carries almost no information (resolution 0.0152 and 0.0057 against
NBA's 0.0483 and 0.0520). Recorded as PREREGISTRATION.md Amendment 3b. Nothing is dropped
and PLAN.md's per-stratum-n reasoning is answered directly: n was never the problem.

**Implementation left for week 5:** NHL strata are still built and reported; only which
sample carries the primary test changes.

**Original item, kept for the record:**

**What:** Re-check whether NHL can carry headline 2's per-stratum n.

**Why, measured in week 4 (chart 2):** Murphy resolution is 0.0147 for NHL 2024-25 and
**0.0055** for NHL 2025-26, against 0.0481 and 0.0517 for NBA. An NHL 2025-26 closing price
improves on "always predict the home team" by 0.005 Brier. NHL closes also span only
0.200-0.825 with 82.6% inside [0.35, 0.65], so the favourite/longshot tails where the
literature reports bias are nearly empty.

**The tension:** PLAN.md's deadline section makes NHL load-bearing for headline 2's
per-stratum n and says it is NOT the right thing to cut. That reasoning was about n, and n is
fine. It did not anticipate that the NHL market would carry almost no information — a market
quoting near the base rate is perfectly calibrated and cannot be shown to be miscalibrated in
an interesting way, whatever its n.

**Do not resolve by dropping NHL** without re-reading that section; the co-headline depends
on it. The likely honest outcome is reporting NHL as a contrast case (a thin, uninformative
market) rather than as a second stratified sample.

**Effort:** S to decide. **Priority:** P2, before week 5-6 strata.

## P1 — The collector's live polling path has never run (before late Oct 2026)

**What:** Wire `upcoming_targets` to real markets, and prove one session against live games.

**Why:** week 4 built the collector and tested every decision it makes about polling — ET
season and daily gates across DST, the midnight-spanning window, the dedup key, the
zero-capture rule, the heartbeat, target selection. What it could NOT test is the poll
itself: the 2026-27 slate does not exist yet, so `scripts/run_collector.py` currently polls
an empty target list and captures zero rows by construction. The missing piece is one
function — resolve each upcoming game to its market's token ids — and it reuses the census's
`schedule` / `slug_candidates` / `resolve.confirm` machinery rather than needing new code.

**Three things that must happen before the season, in order:**

1. **Create the Healthchecks.io check and set `CHIRA_HEARTBEAT_URL` as a repo secret.** The
   provider is chosen (user decision, 2026-09-16) and the code defaults to it, so this is an
   account and a secret, not a code change. Until it is set the dead-man's switch is not
   armed, and an unarmed switch is the failure mode the switch exists for.
2. **Run one real session against live pre-season games and read the rows.** A collector
   whose first live run is also its first unattended run is untested in production.
3. **Decide the keepalive question when the cron is uncommented.** The week-4 slot listed a
   keepalive against the 60-day Actions auto-disable and it was NOT built. Probably correct:
   the clock only disables workflows that are enabled and scheduled, the cron is commented
   out, and this repo takes commits weekly so the window is never approached. A keepalive
   would also duplicate the dead-man's switch, which already catches a disabled workflow as
   silence, and a keepalive that is itself a scheduled workflow faces the same auto-disable
   it exists to prevent. If the repo ever goes quiet for weeks with the cron live, the
   honest fix is an external scheduler, not a self-referential workflow.

**Do not enable the workflow before both.** An enabled cron with no heartbeat is strictly
worse than no cron: it burns quota and produces silence that nobody is watching for.

**Effort:** M (human ~4h / CC ~40min). **Priority:** P1, deadline-driven (late Oct 2026).

## P3 — CI actions target the deprecated Node 20

**What:** Bump `actions/checkout` and `astral-sh/setup-uv` in `.github/workflows/tests.yml`
and `.github/workflows/collector.yml` to versions that run on Node 24.

**Why, observed on the first CI run** (2026-09-16, run 35116703705, green in 50 s): GitHub
annotates every run with "Node.js 20 is deprecated. The following actions target Node.js 20
but are being forced to run on Node.js 24: actions/checkout@v4, astral-sh/setup-uv@v5."
Harmless today and the run passes, but the forcing is a transition measure, not a permanent
one.

**Do not guess the tags.** Check which versions actually exist before bumping. A tag that
does not exist turns a green pipeline red, which is strictly worse than a warning annotation.

**Effort:** XS. **Priority:** P3.

## P2 — Cache sizing (the week-3 census fit, barely)

**What:** A size cap with oldest-first eviction on `Cache`, or trimming cached prices payloads.

**Measured on the full census:** `.http-cache` is **5.1 GB**, not the 3.4 GB projected from
week-2 slices, because NHL 2025-26 markets open ~27 days before the game and carry ~40k
points per series. The store is 460 MB for 145.5M raw price rows. The disk sat at **97%
used with 7.4 GB free** afterwards. `run_census.py` now refuses to start without room for a
sport-season, and a cache write failure degrades instead of killing the run, so this is no
longer blocking; but the next full re-census plus a snapshot on this machine is tight.

**Cheaper alternative, still valid:** trim cached prices payloads to [tip-25h, tip]. The store
now holds every raw series itself, so the cache is no longer the only copy of the data.

**Effort:** S (human ~2h / CC ~15min). **Priority:** P2.

**Related, found cutting the snapshot:** any `ORDER BY` over the raw price table spills its
sort to DuckDB's temp directory next to the store, uncompressed. Over 145.6M rows that was
about 6 GB and it filled the disk. Price rows are now written unsorted and the snapshot
checks free space first, but any future analysis query that sorts the whole raw table will
hit the same wall. Filter to a sport-season or a set of games before sorting.

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
