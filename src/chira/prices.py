"""The narrow price table (PLAN.md T15) and the point-in-time price read.

`price_points` is 145,626,599 rows. Every stated analysis needs four values per
game per side: the close and the T-1h, T-6h and T-24h looks
(PREREGISTRATION.md section 8). T15 exists so modeling and scoring never scan
the raw table, and week 7 is its first consumer, which is why it lands with the
feature store rather than after it.

**Built with a single-pass conditional aggregate, NOT with ASOF JOIN, and that
was measured.** The obvious shape -- cross the 4,661 games with two sides and
four horizons into 37,288 target timestamps and `ASOF LEFT JOIN price_points`
-- filled the disk. DuckDB partitions and sorts the right-hand side of an ASOF
join, and sorting 145.6M rows spilled until `No space left on device`, the same
trap week 3 hit with `ORDER BY` over the same table. The conditional
`arg_max(p, t) FILTER (t <= target)` form needs one streaming hash aggregate
and finishes in **3.3 seconds**. ASOF JOIN is the right tool once the table is
narrow, which is what `price_as_of` below uses it for.

**The build reproduces the census exactly.** These anchors are recomputed in
SQL from the raw series, while `priced.p_home_*` were computed in Python by
`extract.market_features` during the census. All four horizons agree on all
4,661 games, as do `n_pre_tipoff` and `secs_before_tip`
(`tests/test_prices.py`). Two independent implementations of "last quote at or
before the cutoff" landing on identical values is the strongest check available
that neither one drifted.

**Resolution is four anchors, and a read between them is stale on purpose.**
`price_as_of(T)` returns the newest anchor at or before T. Between anchors it
is behind the real market, never ahead of it, so it can understate what was
knowable but can never leak. A finer grain means going back to `price_points`.
"""

from __future__ import annotations

from pathlib import Path

from .snapshot import _sql_path

# (name, seconds before the pre-tipoff cutoff). `close` is the cutoff itself.
HORIZONS: tuple[tuple[str, int], ...] = (
    ("close", 0),
    ("t1h", 3600),
    ("t6h", 6 * 3600),
    ("t24h", 24 * 3600),
)

# Beside the snapshot, never inside it: the snapshot directory is
# content-addressed and its digest is quoted in README.md and
# notes/week3-census.md, so writing a fifth table into it would invalidate
# every reference to `census-20260913-224d6ad985e0`. Same rule as the week-5
# volume patch.
GAME_PRICES = "data/game_prices/game_prices.parquet"

# The pre-tipoff cutoff, restated in SQL. PREREGISTRATION.md Amendment 1: the
# LEAGUE's start time when the census had it, Gamma's otherwise. Every row of
# the week-3 census is 'league'; the branch is kept because the forward
# collector will produce rows that are not.
_CUTOFF = ("CASE WHEN cutoff_source = 'league' THEN league_start_time "
           "ELSE game_start_time END")

_WIDE_SQL = f"""
WITH cut AS (
    SELECT sport, season, game_id,
           epoch(CAST({_CUTOFF} AS TIMESTAMPTZ))::BIGINT AS tip_t
    FROM priced
)
SELECT pp.sport, pp.season, pp.game_id, pp.side,
       any_value(c.tip_t) AS tip_t,
       count(*) FILTER (pp.t <= c.tip_t) AS n_pre_tipoff,
       {{aggs}}
FROM price_points pp
JOIN cut c USING (sport, season, game_id)
GROUP BY 1, 2, 3, 4
"""


def _wide_sql() -> str:
    aggs = ",\n       ".join(
        f"arg_max(pp.p, pp.t) FILTER (pp.t <= c.tip_t - {secs}) AS p_{name},\n"
        f"       max(pp.t)    FILTER (pp.t <= c.tip_t - {secs}) AS t_{name}"
        for name, secs in HORIZONS
    )
    return _WIDE_SQL.format(aggs=aggs)


def _long_sql() -> str:
    """Wide anchors unpivoted to one row per (game, side, horizon).

    Long rather than wide because `price_as_of` needs an ASOF JOIN on the
    quote timestamp, and a wide table has four timestamp columns and nothing
    to join on.
    """
    parts = [
        f"""SELECT sport, season, game_id, side, '{name}' AS horizon,
                   {secs} AS horizon_secs, tip_t, n_pre_tipoff,
                   t_{name} AS quote_t, p_{name} AS p,
                   tip_t - t_{name} AS secs_before_tip
            FROM wide WHERE p_{name} IS NOT NULL"""
        for name, secs in HORIZONS
    ]
    return ("WITH wide AS (\n" + _wide_sql() + "\n)\n"
            + "\nUNION ALL\n".join(parts)
            + "\nORDER BY sport, season, game_id, side, horizon_secs DESC")


def build_game_prices(con, table: str = "game_prices") -> int:
    """Materialise the narrow table into `con`. Returns the row count.

    `con` must already expose `priced` and `price_points`, which is what
    `snapshot.open_snapshot` gives. A NULL anchor is DROPPED rather than
    carried: a market that opened inside the window has no T-24h price, and a
    row saying so would have to be filtered by every reader.
    """
    con.execute(f"CREATE OR REPLACE TABLE {table} AS {_long_sql()}")
    return int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def write_game_prices(con, path: str | Path = GAME_PRICES) -> int:
    """Build and write the narrow table as Parquet. Returns the row count."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = build_game_prices(con, "_game_prices_build")
    con.execute(f"COPY _game_prices_build TO '{_sql_path(p)}' (FORMAT PARQUET)")
    con.execute("DROP TABLE _game_prices_build")
    return n


def attach_game_prices(con, path: str | Path = GAME_PRICES) -> int:
    """Expose the narrow table as a view, empty when the file is absent.

    Same contract as `analysis.attach_volume_patch`: the view always exists so
    a consumer's SQL has one shape, and a missing file degrades to zero rows
    rather than to a query that will not parse.
    """
    p = Path(path)
    if p.is_file():
        con.execute("CREATE OR REPLACE VIEW game_prices AS "
                    f"SELECT * FROM read_parquet('{_sql_path(p)}')")
        return int(con.execute("SELECT count(*) FROM game_prices").fetchone()[0])
    con.execute("""
        CREATE OR REPLACE VIEW game_prices AS
        SELECT NULL::VARCHAR AS sport, NULL::VARCHAR AS season,
               NULL::VARCHAR AS game_id, NULL::VARCHAR AS side,
               NULL::VARCHAR AS horizon, NULL::BIGINT AS horizon_secs,
               NULL::BIGINT AS tip_t, NULL::BIGINT AS n_pre_tipoff,
               NULL::BIGINT AS quote_t, NULL::DOUBLE AS p,
               NULL::BIGINT AS secs_before_tip
        WHERE FALSE
    """)
    return 0


# The ASOF inequality must compare a LEFT column with a RIGHT column, so
# `as_of` is carried into the probe side as a column rather than bound
# directly in the ON clause. Binding it there raises
# "Missing ASOF JOIN inequality", which reads like a syntax error and is not.
_AS_OF_SQL = """
WITH want AS (
    SELECT DISTINCT sport, season, game_id, side, CAST(? AS BIGINT) AS as_of
    FROM game_prices {where}
)
SELECT w.sport, w.season, w.game_id, w.side, w.as_of,
       gp.horizon, gp.quote_t, gp.p, gp.tip_t
FROM want w
ASOF LEFT JOIN game_prices gp
  ON w.sport = gp.sport AND w.season = gp.season
 AND w.game_id = gp.game_id AND w.side = gp.side
 AND w.as_of >= gp.quote_t
ORDER BY w.sport, w.season, w.game_id, w.side
"""


def price_as_of(con, as_of: int, *, sport: str | None = None,
                season: str | None = None) -> list[dict]:
    """The newest anchor at or before `as_of`, per game and side.

    This is the ASOF JOIN E9 asks for, run against the narrow table where it
    costs nothing. `as_of` is unix seconds and is MANDATORY: there is no
    unqualified price read in this module, because the one that leaks is the
    one nobody remembers to qualify.

    A game whose earliest anchor is still in the future comes back with
    `horizon` NULL, which is the honest answer -- the market had not quoted
    anything the caller is allowed to see.
    """
    if not isinstance(as_of, int) or isinstance(as_of, bool):
        raise TypeError(f"as_of must be unix seconds as an int, got {as_of!r}")
    clauses, args = [], []
    if sport:
        clauses.append("sport = ?")
        args.append(sport)
    if season:
        clauses.append("season = ?")
        args.append(season)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = _AS_OF_SQL.format(where=where)
    cur = con.execute(sql, [as_of, *args])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
