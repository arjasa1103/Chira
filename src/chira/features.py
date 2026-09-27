"""Point-in-time feature assembly (PLAN.md Phase 3, E9).

PLAN.md Phase 3: *"Every feature query takes a mandatory `as_of`; no
unqualified read path exists in the API."* That is enforced here structurally,
not by convention: `assemble` has no default for `as_of`, rejects anything that
is not unix seconds, and refuses a target game that has already started. There
is no second function that skips the check.

**What `as_of` actually gates, in two separate layers.** Conflating them is the
leak this module exists to prevent:

- **The schedule is public in advance.** That a team plays in Denver on
  February 3rd is knowable months ahead, so rest days, back-to-backs and travel
  for a *prior* game are visible as soon as that game has started.
- **A result is not public until the game ends.** `RESULT_DELAY_SECONDS` is
  E9's `availability_delay`: a prior game's winner becomes readable at
  `start + delay`, not at `start`. In the backtest this almost never binds,
  because consecutive games for one team are a day apart. **It binds hard for
  the forward collector**, where `as_of` is an hour before a 22:00 ET tipoff
  and another team played at 19:00 the same evening.

**Prices are deliberately absent from the returned frame.** Headline 1 is a
*price-free* model against the closing line, and the cheapest way to guarantee
that is for the feature builder to have no price column at all. The nested test
(Phase 5, model B) joins `prices.price_as_of` itself, which is a visible, one
line act rather than a default.

**`assemble_backtest` is the same SQL with a per-row `as_of`.** Both paths run
one statement, so there is no "fast path" that could drift from the audited
one; `tests/test_features.py` pins them against each other game by game.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .snapshot import _sql_path
from .venues import EARTH_RADIUS_KM, venue_rows

# E9's availability_delay: how long after the opening whistle a result is
# public. These are wall-clock game lengths including stoppages and the usual
# broadcast tail, rounded UP, because over-waiting hides information that was
# available while under-waiting invents information that was not. Overtime
# runs longer and is not modelled; `assemble` takes `result_delay` so the
# sensitivity is one argument away.
RESULT_DELAY_SECONDS: dict[str, int] = {"nba": 8400, "nhl": 9000}

# The window for the schedule-density feature. Seven days is one NBA week and
# spans every back-to-back and three-in-four pattern.
DENSITY_WINDOW_DAYS = 7

FEATURE_COLUMNS: tuple[str, ...] = (
    "sport", "season", "game_id", "et_date", "away", "home", "as_of",
    "away_rest_days", "home_rest_days", "rest_diff",
    "away_b2b", "home_b2b",
    "away_games_7d", "home_games_7d",
    "away_travel_km", "home_travel_km", "travel_diff",
    "away_tz_shift", "home_tz_shift",
    "away_travel_known", "home_travel_known",
    "away_prior_games", "home_prior_games",
    "away_prior_settled", "home_prior_settled",
    "away_prior_wins", "home_prior_wins",
    "away_win_rate", "home_win_rate", "win_rate_diff",
    "away_first_of_season", "home_first_of_season",
)

# Great-circle kilometres between two rows of the venue table, as SQL. It is
# the same formula as `venues.haversine_km` and the two are pinned against
# each other in tests: a second implementation that silently disagrees with
# the first is worse than having only one.
_HAVERSINE = f"""
2 * {EARTH_RADIUS_KM} * asin(sqrt(
    pow(sin(radians({{b}}.lat - {{a}}.lat) / 2), 2)
  + cos(radians({{a}}.lat)) * cos(radians({{b}}.lat))
  * pow(sin(radians({{b}}.lon - {{a}}.lon) / 2), 2)))
"""

_SQL = """
WITH base AS (
    SELECT sport, season, game_id, et_date, away, home, winner,
           coalesce(neutral_site, FALSE) AS neutral_site,
           epoch(CAST(start_time_utc AS TIMESTAMPTZ))::BIGINT AS start_t
    FROM games
),
-- One row per (game, team). The host of an appearance is the venue that
-- matters for travel; for a neutral-site game it is unknown, which is carried
-- rather than guessed.
app AS (
    SELECT sport, season, game_id, et_date, start_t, neutral_site,
           away AS team, home AS host, 'away' AS side, winner
    FROM base
    UNION ALL
    SELECT sport, season, game_id, et_date, start_t, neutral_site,
           home AS team, home AS host, 'home' AS side, winner
    FROM base
),
tt AS (
    SELECT t.sport, t.season, t.game_id, t.et_date, t.as_of,
           coalesce(t.neutral_site, FALSE) AS neutral_site,
           t.home AS host, t.away AS team, 'away' AS tside
    FROM targets t
    UNION ALL
    SELECT t.sport, t.season, t.game_id, t.et_date, t.as_of,
           coalesce(t.neutral_site, FALSE), t.home, t.home, 'home'
    FROM targets t
),
-- The most recent PRIOR appearance, by start time, strictly before as_of.
-- ASOF JOIN is exactly this query (E9); hand-rolling it with a correlated
-- max() was the thing the eng review flagged.
prev AS (
    SELECT tt.*,
           p.game_id AS prev_game_id, p.et_date AS prev_date,
           p.start_t AS prev_start_t, p.host AS prev_host,
           p.side AS prev_side, p.winner AS prev_winner,
           p.neutral_site AS prev_neutral
    FROM tt
    ASOF LEFT JOIN app p
      ON tt.sport = p.sport AND tt.season = p.season AND tt.team = p.team
     AND tt.as_of > p.start_t
),
hist AS (
    SELECT tt.sport, tt.season, tt.game_id, tt.tside,
           count(h.game_id) AS prior_games,
           count(h.game_id) FILTER (
               h.start_t + {delay} <= tt.as_of) AS prior_settled,
           count(h.game_id) FILTER (
               h.start_t + {delay} <= tt.as_of AND h.winner = h.side
           ) AS prior_wins,
           count(h.game_id) FILTER (
               h.start_t >= tt.as_of - {density}) AS games_7d
    FROM tt
    LEFT JOIN app h
      ON h.sport = tt.sport AND h.season = tt.season AND h.team = tt.team
     AND h.start_t < tt.as_of
    GROUP BY 1, 2, 3, 4
),
side_features AS (
    SELECT p.sport, p.season, p.game_id, p.et_date, p.as_of, p.tside,
           date_diff('day', p.prev_date, p.et_date) AS rest_days,
           date_diff('day', p.prev_date, p.et_date) = 1 AS b2b,
           p.prev_game_id IS NULL AS first_of_season,
           -- Travel needs BOTH venues. A neutral-site game at either end has
           -- no venue in the table, so the distance is NULL and the flag says
           -- why, rather than silently becoming "the home team's city".
           CASE WHEN p.prev_game_id IS NULL THEN NULL
                WHEN p.neutral_site OR p.prev_neutral THEN NULL
                ELSE {haversine} END AS travel_km,
           CASE WHEN p.prev_game_id IS NULL THEN NULL
                WHEN p.neutral_site OR p.prev_neutral THEN NULL
                ELSE vb.tz_offset_std - va.tz_offset_std END AS tz_shift,
           p.prev_game_id IS NOT NULL
               AND NOT p.neutral_site AND NOT p.prev_neutral
               AS travel_known,
           h.prior_games, h.prior_settled, h.prior_wins, h.games_7d
    FROM prev p
    JOIN hist h USING (sport, season, game_id, tside)
    LEFT JOIN venues va ON va.sport = p.sport AND va.team = p.prev_host
    LEFT JOIN venues vb ON vb.sport = p.sport AND vb.team = p.host
)
SELECT t.sport, t.season, t.game_id, t.et_date, t.away, t.home, t.as_of,
       a.rest_days AS away_rest_days, h.rest_days AS home_rest_days,
       h.rest_days - a.rest_days AS rest_diff,
       a.b2b AS away_b2b, h.b2b AS home_b2b,
       a.games_7d AS away_games_7d, h.games_7d AS home_games_7d,
       a.travel_km AS away_travel_km, h.travel_km AS home_travel_km,
       h.travel_km - a.travel_km AS travel_diff,
       a.tz_shift AS away_tz_shift, h.tz_shift AS home_tz_shift,
       a.travel_known AS away_travel_known, h.travel_known AS home_travel_known,
       a.prior_games AS away_prior_games, h.prior_games AS home_prior_games,
       a.prior_settled AS away_prior_settled, h.prior_settled AS home_prior_settled,
       a.prior_wins AS away_prior_wins, h.prior_wins AS home_prior_wins,
       CASE WHEN a.prior_settled > 0
            THEN a.prior_wins::DOUBLE / a.prior_settled END AS away_win_rate,
       CASE WHEN h.prior_settled > 0
            THEN h.prior_wins::DOUBLE / h.prior_settled END AS home_win_rate,
       CASE WHEN a.prior_settled > 0 AND h.prior_settled > 0
            THEN h.prior_wins::DOUBLE / h.prior_settled
               - a.prior_wins::DOUBLE / a.prior_settled END AS win_rate_diff,
       a.first_of_season AS away_first_of_season,
       h.first_of_season AS home_first_of_season
FROM targets t
JOIN side_features a
  ON a.sport = t.sport AND a.season = t.season AND a.game_id = t.game_id
 AND a.tside = 'away'
JOIN side_features h
  ON h.sport = t.sport AND h.season = t.season AND h.game_id = t.game_id
 AND h.tside = 'home'
ORDER BY t.sport, t.season, t.game_id
"""


def _sql(result_delay_sql: str) -> str:
    return _SQL.format(
        delay=result_delay_sql,
        density=DENSITY_WINDOW_DAYS * 86400,
        haversine=_HAVERSINE.format(a="va", b="vb").strip(),
    )


def _delay_case(overrides: dict[str, int] | None) -> str:
    """`RESULT_DELAY_SECONDS` as a SQL expression on tt.sport."""
    table = dict(RESULT_DELAY_SECONDS)
    table.update(overrides or {})
    for sport, secs in table.items():
        if not isinstance(secs, int) or isinstance(secs, bool) or secs < 0:
            raise ValueError(f"result delay for {sport!r} must be a "
                             f"non-negative int, got {secs!r}")
    arms = " ".join(f"WHEN '{s}' THEN {v}" for s, v in sorted(table.items()))
    # An unknown sport gets the LONGEST configured delay rather than zero:
    # defaulting to zero would make every result instantly public, which is
    # the leak, and silently.
    return f"(CASE tt.sport {arms} ELSE {max(table.values())} END)"


def attach_venues(con, table: str = "venues") -> int:
    """Materialise the vendored venue table into `con`. Returns the row count.

    A table rather than a view: it is 62 rows of Python literals, and the
    joins in `_SQL` hit it twice per appearance.
    """
    rows = venue_rows()
    con.execute(f"CREATE OR REPLACE TABLE {table} ("
                "sport VARCHAR, team VARCHAR, lat DOUBLE, lon DOUBLE, "
                "city VARCHAR, tz_offset_std DOUBLE)")
    con.executemany(
        f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?)",
        [(r["sport"], r["team"], r["lat"], r["lon"], r["city"],
          float(r["tz_offset_std"])) for r in rows])
    return len(rows)


def to_unix(value: datetime) -> int:
    """An aware datetime to unix seconds. A naive one is refused.

    Same rule as `extract._parse_gst` and `upcoming.parse_start`: a naive
    timestamp's `.timestamp()` is read in the host zone, so the same call
    would place `as_of` at a different instant on a laptop and in CI.
    """
    if value.tzinfo is None:
        raise ValueError("as_of must be timezone-aware; a naive datetime is "
                         "read in the host zone and would move under TZ=")
    return int(value.timestamp())


def _check_as_of(as_of: object) -> int:
    if isinstance(as_of, datetime):
        return to_unix(as_of)
    if isinstance(as_of, bool) or not isinstance(as_of, int):
        raise TypeError("as_of is mandatory and must be unix seconds as an "
                        f"int (or an aware datetime), got {as_of!r}")
    return as_of


def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def assemble(con, targets: list[dict], *, as_of,
             result_delay: dict[str, int] | None = None) -> list[dict]:
    """Features for `targets`, using only what was knowable at `as_of`.

    `targets` carries the games to predict -- sport, season, game_id, et_date,
    away, home, and optionally neutral_site. It is an ARGUMENT rather than a
    store read on purpose: in production it comes from `upcoming.py`, and it
    is what makes the leakage canary meaningful, because the target set stays
    fixed while the store behind it is truncated.

    `con` must expose `games`; `attach_venues` is called here if `venues` is
    not already present.

    Raises on a target that has already started at `as_of`. A pre-game feature
    vector for a game in progress is not a thing this module will build, and
    allowing it would let a game become its own previous game.
    """
    at = _check_as_of(as_of)
    if not targets:
        return []
    con.execute("CREATE OR REPLACE TEMP TABLE targets AS "
                "SELECT * FROM (VALUES " + ", ".join(
                    ["(?, ?, ?, CAST(? AS DATE), ?, ?, ?, CAST(? AS BIGINT))"]
                    * len(targets)) +
                ") AS t(sport, season, game_id, et_date, away, home, "
                "neutral_site, as_of)",
                [v for t in targets for v in (
                    t["sport"], t["season"], str(t["game_id"]), t["et_date"],
                    t["away"], t["home"], bool(t.get("neutral_site", False)),
                    at)])
    return _assemble_from_targets(con, result_delay)


def _assemble_from_targets(con, result_delay, *, into: str | None = None):
    if not con.execute("SELECT count(*) FROM duckdb_tables() "
                       "WHERE table_name = 'venues'").fetchone()[0]:
        attach_venues(con)
    started = con.execute(
        "SELECT count(*) FROM targets t JOIN games g "
        "  ON g.sport = t.sport AND g.season = t.season "
        " AND g.game_id = t.game_id "
        "WHERE epoch(CAST(g.start_time_utc AS TIMESTAMPTZ)) < t.as_of"
    ).fetchone()[0]
    if started:
        raise ValueError(
            f"{started} target game(s) had already started at the requested "
            "as_of. Features here are pre-game only; a game that has started "
            "would become its own previous game.")
    sql = _sql(_delay_case(result_delay))
    if into is None:
        return _rows(con.execute(sql))
    con.execute(f"CREATE OR REPLACE TABLE {into} AS {sql}")
    return int(con.execute(f"SELECT count(*) FROM {into}").fetchone()[0])


def assemble_backtest(con, *, lead_seconds: int = 0,
                      sport: str | None = None, season: str | None = None,
                      result_delay: dict[str, int] | None = None,
                      into: str | None = None):
    """Every game in the store, each assembled at its own tipoff minus a lead.

    This is what Phase 4 trains on. `lead_seconds` is how far before the
    opening whistle the forecast is made; 0 means "at the whistle", which is
    the closing-line comparison's own reference point.

    It is the SAME statement as `assemble`, with a per-row `as_of` instead of
    a constant, so the two cannot drift. `tests/test_features.py` runs a
    sample of games through both and requires identical rows.

    With `into`, the result is left in that table and the row count is
    returned, so a 5,084-row frame is not round-tripped through Python only
    to be written straight back out as Parquet.
    """
    if not isinstance(lead_seconds, int) or isinstance(lead_seconds, bool) \
            or lead_seconds < 0:
        raise ValueError("lead_seconds must be a non-negative int; a negative "
                         "lead would place as_of after the opening whistle")
    clauses, args = [], []
    if sport:
        clauses.append("sport = ?")
        args.append(sport)
    if season:
        clauses.append("season = ?")
        args.append(season)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE targets AS
        SELECT sport, season, game_id, et_date, away, home,
               coalesce(neutral_site, FALSE) AS neutral_site,
               epoch(CAST(start_time_utc AS TIMESTAMPTZ))::BIGINT - {lead_seconds}
                   AS as_of
        FROM games {where}
    """, args)
    return _assemble_from_targets(con, result_delay, into=into)


FEATURES_PARQUET = "data/features/features.parquet"


def write_backtest(con, path: str | Path = FEATURES_PARQUET, **kw) -> int:
    """Assemble the whole backtest frame and write it as Parquet.

    Beside the snapshot, never inside it, for the same reason `game_prices`
    is: the snapshot directory is content-addressed and its digest is quoted
    in README.md.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = assemble_backtest(con, into="_features_build", **kw)
    con.execute(f"COPY _features_build TO '{_sql_path(p)}' (FORMAT PARQUET)")
    con.execute("DROP TABLE _features_build")
    return n


def attach_features(con, path: str | Path = FEATURES_PARQUET) -> int:
    """Expose a written feature frame as a view. Returns the row count."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(
            f"no feature frame at {p}; run scripts/run_features.py. There is "
            "deliberately no empty-view fallback here: an empty feature frame "
            "would train a model on nothing rather than fail.")
    con.execute("CREATE OR REPLACE VIEW features AS "
                f"SELECT * FROM read_parquet('{_sql_path(p)}')")
    return int(con.execute("SELECT count(*) FROM features").fetchone()[0])
