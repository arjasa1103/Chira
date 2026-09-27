# Week 7 — the feature store, and the canary that guards it

Week 7's second half: PLAN.md T15 (the narrow price table) and E9 (point-in-time
assembly with a mandatory `as_of`). They land together because the feature store is
T15's first consumer and building it against 145.6M raw rows first would mean building
it twice.

**Nothing here reads a price into a feature.** Headline 1 is a *price-free* model
against the closing line, and the cheapest guarantee is structural: `features.py` has no
price column, and a test asserts it has none. The nested test (Phase 5, model B) joins
`prices.price_as_of` itself, which is one visible line rather than a default.

## The obvious way to build the narrow table ran out of memory

Cross 4,661 games with two sides and four horizons into 37,288 target timestamps,
`ASOF LEFT JOIN price_points`, done. It failed:

```
IO Error: Could not write file ".tmp/duckdb_temp_storage_DEFAULT-1.tmp":
No space left on device
```

**The first explanation written here was too strong.** It said DuckDB sorts the right
side of an ASOF join, so ASOF is out of budget on this table, full stop. Measured, the
truth is narrower, and the narrower version is the useful one.

ASOF resolves "the last row at or before t" by keeping the **build** side materialised
and ordered by (equality keys, t). The probe side here is 37,288 rows. The build side is
the whole of `price_points`, because nothing is pushed into the scan:

```
┌──────────────────┐        ┌──────────────┐
│    ASOF_JOIN     │        │ READ_PARQUET │
│  sport = sport   ├────────┤ game_id,side │
│  target_t >= t   │        │ t, p, season │
└──────────────────┘        └──────────────┘
```

So the cost is set by the build side alone. Measured with a 500 MB memory limit and a
6 GB temp cap, spilling the rest:

| build side | rows | peak temp | wall | result |
|---|---|---|---|---|
| nhl 2024-25 | 11,996,280 | 0.45 GB | 1.2 s | ok |
| both leagues, 2024-25 | 26,830,874 | 1.36 GB | 3.5 s | ok |
| all nhl | 108,125,584 | hit the cap | 21.7 s | **out of memory** |
| everything | 145,626,599 | hit the cap | 19.1 s | **out of memory** |

Resident plus spilled comes to **~70-80 bytes per row** — four VARCHARs carried as
16-byte inline `string_t` values, plus a BIGINT and a DOUBLE — so the full table is a
**~10 GB working set on a machine with 8.6 GB of RAM**. The threshold sits somewhere
between 27M and 108M rows.

**So ASOF is not the wrong operator, it is the wrong scale.** The identical query
against one pre-filtered sport-season runs in 1.2 s and never touches the disk. Two
fixes were available. Hash-join `price_points` to the tips first and keep only
`t BETWEEN tip - 25h AND tip`, which streams, then ASOF the remainder. Or notice that
the four anchor times are **known constants per game**, which makes the whole thing an
aggregate:

```sql
arg_max(pp.p, pp.t) FILTER (pp.t <= c.tip_t - 3600) AS p_t1h
```

A `HASH_GROUP_BY` over 9,322 groups holds one accumulator set per group and discards
every row as it passes. Nothing is ordered and nothing is retained, and it finishes in
**3.3 s** on the full table. That is the build that shipped.

**One hypothesis tested and killed.** The failing run left `preserve_insertion_order` at
its default while the working one had it off, which is a real confound and would have
been a much cheaper fix. It is not the cause: under the same caps both settings fail,
at 10.0 s and 12.7 s.

ASOF JOIN is still used, in `prices.price_as_of` and in `features.py`, where the build
sides are 37k and 5k rows.

## The narrow table reproduces the census exactly

The four anchors are recomputed in SQL from the raw series; `priced.p_home_*` were
computed in Python by `extract.market_features` during the census. Two independent
implementations of "last quote at or before the cutoff":

| Column | Games compared | Disagreements |
|---|---|---|
| `p_home_close` | 4,661 | **0** |
| `p_home_t1h` | 4,661 | **0** |
| `p_home_t6h` | 4,661 | **0** |
| `p_home_t24h` | 4,661 | **0** |
| `n_pre_tipoff` | 4,661 | **0** |
| `secs_before_tip` | 4,661 | **0** |

`scripts/build_game_prices.py` re-runs the close comparison every build and exits
non-zero on any disagreement, so this cannot rot quietly.

**The reduction.** 145,626,599 rows / 162 MB become 36,976 rows / 248 KB, a factor of
~3,900. The away leg is now available at every horizon, which the census only carried
for the home side: complementarity holds at all four (4,659 of 4,661 exact at the close,
the two exceptions off by 0.01 and 0.005), and only 55% of home/away anchor pairs share
a timestamp, which is carry-forward doing its work.

Anchors missing because the market opened inside the window: 0 at the close, 2 at T-1h,
42 at T-6h, 268 at T-24h, out of 9,322 game-sides. They are dropped rather than stored
as NULL rows, so no reader has to filter them.

## `as_of` gates two different things, and conflating them is the leak

- **The schedule is public in advance.** That a team plays in Denver on February 3rd is
  knowable months ahead, so rest, back-to-backs and travel from a *prior* game are
  visible as soon as that game has started.
- **A result is not public until the game ends.** `RESULT_DELAY_SECONDS` is E9's
  `availability_delay`: NBA 8,400 s, NHL 9,000 s, rounded up, because over-waiting hides
  information that existed while under-waiting invents information that did not.

**Measured: the delay never binds in the backtest.** 0 of 5,084 games have a prior
result that was still unsettled at tipoff, because a team's previous game is a day
earlier. That is not an argument for dropping it — it binds hard for the forward
collector, where `as_of` is an hour before a 22:00 ET tipoff and other teams played at
19:00 the same evening. An unknown sport gets the *longest* configured delay, never
zero, because a zero default would publish every result instantly and silently.

## The canary, in three forms

PLAN.md Phase 3 pre-registers it: *"a query with `as_of=T` returns byte-identical
results against a DB truncated at T and a DB holding all later rows."*

1. **Truncation.** Same targets, one store holding everything, one holding only games
   that had started by T. Identical.
2. **The sharper form.** A game the store *holds*, happening between T and the target's
   tipoff, must not move a single feature. Identical.
3. **The canary can die.** A canary that cannot fail is decoration. Move `as_of` past
   that extra game and the same comparison must now *differ* — it does, which proves the
   two stores were distinguishable all along and that form 2 was a real result.

Run on the real census as well as on fakes: `as_of` 2025-01-15T23:00Z, 31 target games
in the next 48 hours, 1,289 of 5,084 games visible in the truncated store,
byte-identical.

Three more structural guards, because a canary only catches what it is pointed at:

- `as_of` has **no default**, rejects a float, a string, a bool and a naive datetime,
  and accepts an aware datetime only through an explicit conversion.
- A target that has **already started** is refused. Otherwise a game becomes its own
  previous game.
- `assemble` (one `as_of`) and `assemble_backtest` (per-game `as_of`) are **the same SQL
  statement**, and a test runs every game through both and requires identical rows.
  There is no fast path that could drift from the audited one.

## The venue table, and what it cannot see

62 hand-vendored rows, team → arena-area coordinates → city → standard UTC offset.
Vendored rather than fetched for the reason `nhl.NHL_TEAMS` is: a half-failed fetch
silently *shortens* the table, and a short venue table does not fail — it returns no
travel for the teams it dropped, which reads as "this team never travels". Ten pairs are
pinned against published great-circle distances (`nyr`-`njd` 15 km through `sea`-`fla`
4,357 km) and the SQL haversine is pinned against the Python one.

**`neutral_site` is only as good as its source, and for the NBA there is no source.**
`nhl.nhl_games` reads `neutralSite` and flags 10 games across the two seasons — six in
2024-25 and four in 2025-26, in the pattern international series and outdoor games
produce. `schedule.nba_games` never
sets the field at all, so every one of the 2,460 NBA rows carries FALSE *by
construction, not by measurement*. Travel for any NBA game played away from the nominal
home team's city is therefore wrong, and the feature store cannot tell. It is recorded
as a gap rather than guessed at: a neutral-site game at either end yields
`travel_km = NULL` and `travel_known = FALSE`, never the home team's city.

## A finding the feature store produced on its first run

Back-to-backs are **not symmetric in the NHL**:

| | away b2b | home b2b |
|---|---|---|
| NBA 2024-25 | 18.6% | 18.0% |
| NBA 2025-26 | 18.4% | 17.5% |
| **NHL 2024-25** | **21.1%** | **9.2%** |
| **NHL 2025-26** | **20.5%** | **12.3%** |

The NBA schedules the second leg of a back-to-back at home about as often as on the
road. The NHL puts it on the road roughly twice as often. **Consequence for Phase 4: in
the NHL a back-to-back dummy is partly a road dummy**, so a b2b coefficient fitted
without the interaction absorbs part of home advantage. PLAN.md Phase 4 already keeps
rest, back-to-back and travel global rather than per team; this says the NHL b2b term
also needs the home/away interaction, or it needs to be read as a joint effect and said
so.

Sanity checks that passed on the way: 30 NBA and 32 NHL first-of-season rows per season,
exactly one per team; median travel 985-1,012 km NBA and 711 km NHL; longest leg 4,357
km (`fla` to `sea`); time-zone shifts spanning exactly ±3 hours.

## Still open

- **E7 (the availability slot) is date-locked** and cannot be pulled forward. It needs
  live regular-season injury reports; the NBA tips 2026-10-20.
- **The NBA `neutral_site` flag has no source.** Small (a handful of games a season),
  but it silently corrupts travel for exactly the most extreme trips.
- **The cron is still commented out** and the heartbeat ping is still unproven
  end-to-end. The collector workflow now takes a `once` input so a proof dispatch runs
  one cycle instead of holding a runner for 5h30.
- **Overtime is not modelled** in `RESULT_DELAY_SECONDS`. Immaterial in the backtest (it
  never binds), and one argument away from a sensitivity run when the collector makes it
  matter.
