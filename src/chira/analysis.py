"""The analysis frame: the snapshot read into exactly the rows a chart may use.

Everything from week 4 on reads the immutable snapshot, never the live store and
never the API (PREREGISTRATION.md section 1). This module is the only door, so
the pre-registered conventions are enforced in one place instead of being
re-implemented per chart:

- **Home side only, one observation per game** (section 2). Plotting both
  outcome tokens would double-count every game and force artificial symmetry
  about 0.5, hiding the asymmetry the chart exists to show.
- **Canonical row order.** Equal-count binning is input-order dependent when
  prices tie, which they do heavily (2,047 of 4,661 closes are carried forward),
  and `tests/test_week1_facts.py` measured ECE 0.367 vs 0.177 on the same
  multiset under a permutation. Every query here is `ORDER BY sport, season,
  game_id`, and `assert_canonical` is called before any metric is computed.
- **The label comes from the LEAGUE** (`games.winner`), never from the market's
  own `outcomePrices`. The market's winner is what the gate's label-agreement
  check tests against; using it here would make that check circular.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .snapshot import _sql_path, open_snapshot

# The four looks at one sample (PREREGISTRATION.md section 8). They are a
# repeated measure, not four independent observations, which is why a bootstrap
# over more than one of them must resample GAMES and reuse the draw.
LOOKS = ("p_close", "p_t1h", "p_t6h", "p_t24h")

# The week-5 side table (scripts/fetch_volume_patch.py). It carries volume for
# games the census recorded as NULL, plus an explicit "no volume exists" marker,
# and it lives beside the snapshot rather than inside it so the frozen store
# digest quoted in README.md and notes/week3-census.md stays valid.
VOLUME_PATCH = "data/volume_patch/volume_patch.parquet"

_FRAME_SQL = """
SELECT
    p.sport, p.season, p.game_id, g.et_date,
    p.p_home_close       AS p_close,
    p.p_home_t1h         AS p_t1h,
    p.p_home_t6h         AS p_t6h,
    p.p_home_t24h        AS p_t24h,
    p.p_home_close_gamma AS p_close_gamma,
    CASE WHEN g.winner = 'home' THEN 1.0 ELSE 0.0 END AS y,
    -- Volume, with the patch folded in. 'market' is the census's own value,
    -- 'volumeClob' is a value the census missed (identical quantity, measured),
    -- and 'absent' means Gamma has no per-market volume at all -- those games
    -- are excluded from the liquidity axis by PREREGISTRATION.md Amendment 4
    -- and are never proxied.
    COALESCE(p.volume, vp.volume_recovered) AS volume,
    CASE WHEN p.volume IS NOT NULL THEN 'market'
         WHEN vp.volume_recovered IS NOT NULL THEN vp.volume_source
         ELSE 'absent' END AS volume_source,
    p.stale_flat_run, p.cutoff_source, p.gamma_delta_min,
    p.secs_before_tip, p.convention, p.market_type,
    -- Integer division, NOT CAST(x/7 AS INTEGER): the cast rounds to nearest,
    -- which would pull the back half of every week into the next one.
    (date_diff('day', s.season_start, g.et_date) // 7) + 1 AS week_of_season
FROM priced p
JOIN games g USING (sport, season, game_id)
JOIN (SELECT sport, season, min(et_date) AS season_start
      FROM games GROUP BY sport, season) s USING (sport, season)
LEFT JOIN volume_patch vp
       ON vp.sport = p.sport AND vp.season = p.season AND vp.game_id = p.game_id
{where}
ORDER BY p.sport, p.season, p.game_id
"""


def _scope(sport: str | None, season: str | None) -> tuple[str, list]:
    clauses, args = [], []
    if sport:
        clauses.append("p.sport = ?")
        args.append(sport)
    if season:
        clauses.append("p.season = ?")
        args.append(season)
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), args


def attach_volume_patch(con, path: str | Path = VOLUME_PATCH) -> int:
    """Expose the volume side table as a view. Returns the row count.

    Always creates the view, empty when the file is absent, so the frame's SQL
    has one shape and a missing patch degrades to "the census's own volume"
    rather than to a query that will not parse.
    """
    p = Path(path)
    if p.is_file():
        con.execute("CREATE OR REPLACE VIEW volume_patch AS "
                    f"SELECT * FROM read_parquet('{_sql_path(p)}')")
        return int(con.execute("SELECT count(*) FROM volume_patch").fetchone()[0])
    con.execute("""
        CREATE OR REPLACE VIEW volume_patch AS
        SELECT NULL::VARCHAR AS sport, NULL::VARCHAR AS season,
               NULL::VARCHAR AS game_id, NULL::DOUBLE AS volume_recovered,
               NULL::VARCHAR AS volume_source
        WHERE FALSE
    """)
    return 0


def open_frame(snapshot: str | Path, *, verify: bool = True,
               patch: str | Path | None = VOLUME_PATCH):
    """Open the snapshot read-only. Checksums are verified unless told not to."""
    con = open_snapshot(snapshot, verify=verify)
    attach_volume_patch(con, patch if patch is not None else "")
    return con


def frame(con, sport: str | None = None, season: str | None = None) -> dict:
    """One row per priced game, home side, canonically ordered.

    Returns columns as arrays rather than a DataFrame: pandas is not a
    dependency, and the callers need numpy anyway.
    """
    where, args = _scope(sport, season)
    # The frame joins the volume side table, so make sure it exists. A caller
    # that built a connection itself (every test here, and any notebook) would
    # otherwise get "Table with name volume_patch does not exist"; an empty view
    # is the right default, meaning "the census's own volume, no patch".
    present = con.execute(
        "SELECT count(*) FROM duckdb_views() WHERE view_name = 'volume_patch' "
        "UNION ALL SELECT count(*) FROM duckdb_tables() "
        "WHERE table_name = 'volume_patch'").fetchall()
    if not any(row[0] for row in present):
        attach_volume_patch(con, "")
    cur = con.execute(_FRAME_SQL.format(where=where), args)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    if not rows:
        raise ValueError(f"empty frame for sport={sport} season={season}")
    out = {c: np.array([r[i] for r in rows], dtype=object) for i, c in enumerate(cols)}
    for c in (*LOOKS, "p_close_gamma", "y", "volume"):
        # object -> float, with None becoming nan so "missing" stays missing
        # instead of becoming 0.0. A 0.0 volume and an absent volume are
        # different facts and one of them is a $0 market.
        out[c] = np.array([np.nan if v is None else float(v) for v in out[c]])
    out["week_of_season"] = out["week_of_season"].astype(int)
    assert_canonical(out)
    return out


def assert_canonical(f: dict) -> None:
    """Refuse a frame that is not in (sport, season, game_id) order.

    Not defensive decoration: binning ties depends on row order, so an
    out-of-order frame silently changes every binned metric downstream.
    """
    key = list(zip(f["sport"], f["season"], f["game_id"], strict=True))
    if key != sorted(key):
        raise ValueError("frame is not in canonical (sport, season, game_id) order")


def look(f: dict, name: str) -> tuple[np.ndarray, np.ndarray]:
    """(p, y) for one look, with games missing that look dropped.

    T-24h is null on 100 NBA and 33 NHL 2024-25 games whose markets opened less
    than a day before tipoff, so the looks do NOT share a denominator. The
    dropped count is returned by `look_coverage` so a chart can say so instead
    of quietly comparing curves built on different games.
    """
    if name not in LOOKS:
        raise ValueError(f"unknown look {name!r}; expected one of {LOOKS}")
    p, y = f[name], f["y"]
    keep = ~np.isnan(p)
    return p[keep], y[keep]


def look_coverage(f: dict) -> dict:
    return {name: {"available": int((~np.isnan(f[name])).sum()),
                   "missing": int(np.isnan(f[name]).sum())}
            for name in LOOKS}


def coverage_by_week(con, sport: str, season: str) -> list[dict]:
    """Chart 1's data: every SCHEDULED game bucketed by week of season.

    The denominator is `games`, not `priced`, and the identity
    `scheduled == priced + missed` is asserted per week. The coverage chart is
    a ratio, so a lost denominator row moves it without anything looking
    broken; that is the whole reason the store carries a `misses` table.

    `volume_missing` is reported beside the median because Gamma returned no
    volume field for a contiguous block of March 2026 games in both sports.
    A median over the remainder is still the right summary, but it is a median
    over a biased subset of that window and must not be printed bare.
    """
    rows = con.execute(
        """
        SELECT w.week_of_season,
               count(*)                                              AS scheduled,
               count(p.game_id)                                      AS priced,
               count(m.game_id)                                      AS missed,
               median(p.volume)                                      AS median_volume,
               sum(CASE WHEN p.game_id IS NOT NULL AND p.volume IS NULL
                        THEN 1 ELSE 0 END)                           AS volume_missing,
               min(w.et_date)                                        AS week_start
        FROM (SELECT g.*, (date_diff('day', s.season_start, g.et_date) // 7)
                          + 1 AS week_of_season
              FROM games g
              JOIN (SELECT sport, season, min(et_date) AS season_start
                    FROM games GROUP BY sport, season) s USING (sport, season)
              WHERE g.sport = ? AND g.season = ?) w
        LEFT JOIN priced p USING (sport, season, game_id)
        LEFT JOIN misses m USING (sport, season, game_id)
        GROUP BY w.week_of_season
        ORDER BY w.week_of_season
        """, [sport, season]).fetchall()
    out = []
    for week, sched, priced, missed, med, vmiss, start in rows:
        if priced + missed != sched:
            raise ValueError(
                f"{sport} {season} week {week}: {priced} priced + {missed} missed "
                f"!= {sched} scheduled; the reconciliation identity is broken")
        out.append({"week": int(week), "week_start": str(start), "scheduled": int(sched),
                    "priced": int(priced), "missed": int(missed),
                    "median_volume": None if med is None else float(med),
                    "volume_missing": int(vmiss)})
    return out


def sport_seasons(con) -> list[tuple[str, str]]:
    return [(s, se) for s, se in con.execute(
        "SELECT DISTINCT sport, season FROM priced ORDER BY sport, season").fetchall()]


def price_pool(con, sport: str | None = None, season: str | None = None) -> np.ndarray:
    """Closing prices as an empirical pool, for the section-4 null simulation."""
    where, args = _scope(sport, season)
    sql = f"SELECT p.p_home_close FROM priced p {where} ORDER BY p.sport, p.season, p.game_id"
    return np.array([r[0] for r in con.execute(sql, args).fetchall()])
