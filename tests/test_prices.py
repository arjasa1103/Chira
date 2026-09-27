"""The narrow `game_prices` table (T15) and the point-in-time price read.

Offline: an in-memory DuckDB carrying the two snapshot views the build reads,
because `data/` is gitignored and a test that depended on the real snapshot
would pass here and fail on a clean clone. The one thing these fakes cannot
check is that the build reproduces the census on the real 145.6M rows; that is
`scripts/build_game_prices.py`, which prints the disagreement count and exits
non-zero if it is not zero (measured 2026-09-27: 0 of 4,661).
"""

from __future__ import annotations

import duckdb
import pytest

from chira.prices import (
    HORIZONS,
    attach_game_prices,
    build_game_prices,
    price_as_of,
    write_game_prices,
)

TIP = 1_700_000_000  # an arbitrary fixed epoch; nothing here is date-sensitive


def build(priced, points):
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='UTC'")
    con.execute("""CREATE TABLE priced (sport VARCHAR, season VARCHAR,
                   game_id VARCHAR, cutoff_source VARCHAR,
                   league_start_time VARCHAR, game_start_time VARCHAR)""")
    con.execute("""CREATE TABLE price_points (sport VARCHAR, season VARCHAR,
                   game_id VARCHAR, side VARCHAR, t BIGINT, p DOUBLE)""")
    if priced:
        con.executemany("INSERT INTO priced VALUES (?,?,?,?,?,?)", priced)
    if points:
        con.executemany("INSERT INTO price_points VALUES (?,?,?,?,?,?)", points)
    return con


def iso(epoch):
    """The snapshot stores cutoffs as ISO text with an explicit +00 offset."""
    import datetime as dt
    return dt.datetime.fromtimestamp(epoch, dt.UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def one_game(cutoff_source="league", tip=TIP):
    league = iso(tip) if cutoff_source == "league" else None
    gamma = iso(tip + 6 * 3600) if cutoff_source == "league" else iso(tip)
    return [("nba", "2024-25", "1", cutoff_source, league, gamma)]


def series(offsets_and_prices, side="home"):
    return [("nba", "2024-25", "1", side, TIP - off, p)
            for off, p in offsets_and_prices]


class TestTheAnchors:
    def test_each_anchor_is_the_last_quote_at_or_before_its_horizon(self):
        con = build(one_game(), series([
            (30 * 3600, 0.10),   # before T-24h
            (24 * 3600, 0.20),   # exactly T-24h: at-or-before, so it counts
            (7 * 3600, 0.30),    # before T-6h
            (2 * 3600, 0.40),    # before T-1h
            (60, 0.50),          # the close
        ]))
        build_game_prices(con)
        got = dict(con.execute(
            "SELECT horizon, p FROM game_prices WHERE side='home'").fetchall())
        assert got == {"t24h": 0.20, "t6h": 0.30, "t1h": 0.40, "close": 0.50}

    def test_post_tipoff_points_never_reach_the_close(self):
        """The raw series carries in-game points; the close is pre-tipoff."""
        con = build(one_game(), series([(600, 0.44), (-600, 0.98)]))
        build_game_prices(con)
        assert con.execute("SELECT p FROM game_prices WHERE horizon='close'"
                           ).fetchone()[0] == 0.44

    def test_an_anchor_with_no_quote_yet_is_dropped_not_nulled(self):
        """A market that opened inside the window has no T-24h price. A row
        saying so would have to be filtered by every reader."""
        con = build(one_game(), series([(2 * 3600, 0.4), (60, 0.5)]))
        build_game_prices(con)
        assert set(con.execute("SELECT DISTINCT horizon FROM game_prices"
                               ).fetchall()) == {("close",), ("t1h",)}

    def test_quote_t_and_secs_before_tip_describe_the_quote_used(self):
        con = build(one_game(), series([(90, 0.5)]))
        build_game_prices(con)
        row = con.execute("SELECT quote_t, secs_before_tip, tip_t FROM "
                          "game_prices WHERE horizon='close'").fetchone()
        assert row == (TIP - 90, 90, TIP)

    def test_both_sides_are_built(self):
        con = build(one_game(),
                    series([(60, 0.4)]) + series([(60, 0.6)], side="away"))
        build_game_prices(con)
        assert dict(con.execute("SELECT side, p FROM game_prices "
                                "WHERE horizon='close'").fetchall()) == {
            "home": 0.4, "away": 0.6}

    def test_the_gamma_cutoff_is_used_when_the_census_had_no_league_time(self):
        """Amendment 1's fallback. Every week-3 row is 'league'; the forward
        collector will produce rows that are not."""
        con = build(one_game("gamma"), series([(60, 0.5), (-60, 0.9)]))
        build_game_prices(con)
        assert con.execute("SELECT p FROM game_prices WHERE horizon='close'"
                           ).fetchone()[0] == 0.5

    def test_rows_are_canonically_ordered_longest_horizon_first(self):
        con = build(one_game(), series([(30 * 3600, 0.1), (60, 0.5)]))
        build_game_prices(con)
        assert [r[0] for r in con.execute(
            "SELECT horizon FROM game_prices WHERE side='home'").fetchall()] == [
            "t24h", "t6h", "t1h", "close"]

    def test_n_pre_tipoff_counts_only_pre_tipoff_points(self):
        con = build(one_game(), series([(600, 0.4), (60, 0.5), (-60, 0.9)]))
        build_game_prices(con)
        assert con.execute("SELECT DISTINCT n_pre_tipoff FROM game_prices "
                           "WHERE side='home'").fetchone()[0] == 2


class TestTheViewContract:
    def test_a_missing_file_gives_an_empty_view_not_a_broken_query(self):
        """Same contract as analysis.attach_volume_patch: one query shape."""
        con = duckdb.connect(":memory:")
        assert attach_game_prices(con, "does/not/exist.parquet") == 0
        assert con.execute("SELECT count(*) FROM game_prices").fetchone()[0] == 0
        assert price_as_of(con, TIP) == []

    def test_the_empty_view_carries_every_real_column(self):
        con = duckdb.connect(":memory:")
        attach_game_prices(con, "does/not/exist.parquet")
        empty = {d[0] for d in con.execute(
            "SELECT * FROM game_prices").description}
        real = build(one_game(), series([(60, 0.5)]))
        build_game_prices(real)
        assert empty == {d[0] for d in real.execute(
            "SELECT * FROM game_prices").description}

    def test_round_trip_through_parquet(self, tmp_path):
        con = build(one_game(), series([(30 * 3600, 0.1), (60, 0.5)]))
        out = tmp_path / "gp.parquet"
        assert write_game_prices(con, out) == 4
        fresh = duckdb.connect(":memory:")
        assert attach_game_prices(fresh, out) == 4
        assert fresh.execute("SELECT p FROM game_prices WHERE horizon='close'"
                             ).fetchone()[0] == 0.5


class TestPriceAsOf:
    def setup_method(self):
        self.con = build(one_game(), series([
            (24 * 3600, 0.20), (6 * 3600, 0.30), (3600, 0.40), (60, 0.50)]))
        build_game_prices(self.con)

    def test_it_returns_the_newest_anchor_at_or_before_as_of(self):
        assert price_as_of(self.con, TIP - 3600)[0]["horizon"] == "t1h"
        assert price_as_of(self.con, TIP - 3600)[0]["p"] == 0.40

    def test_it_never_returns_a_later_anchor(self):
        """The whole point. A read one second before the T-1h quote must not
        see it."""
        got = price_as_of(self.con, TIP - 3601)[0]
        assert got["horizon"] == "t6h" and got["p"] == 0.30

    def test_before_the_first_anchor_the_answer_is_null_not_the_first_anchor(self):
        got = price_as_of(self.con, TIP - 48 * 3600)[0]
        assert got["horizon"] is None and got["p"] is None
        assert got["game_id"] == "1"   # the game is still listed

    def test_between_anchors_it_is_stale_and_never_early(self):
        """Resolution is four anchors. Staleness understates what was
        knowable; it can never leak."""
        assert price_as_of(self.con, TIP - 2 * 3600)[0]["horizon"] == "t6h"

    def test_as_of_is_mandatory_and_must_be_unix_seconds(self):
        for bad in (None, "2024-01-01", 1.5, True):
            with pytest.raises(TypeError, match="as_of"):
                price_as_of(self.con, bad)

    def test_scoping_by_sport_and_season(self):
        assert len(price_as_of(self.con, TIP, sport="nba")) == 1   # home only here
        assert price_as_of(self.con, TIP, sport="nhl") == []
        assert price_as_of(self.con, TIP, season="1999-00") == []


def test_horizons_are_descending_and_include_the_close():
    secs = [s for _, s in HORIZONS]
    assert secs[0] == 0 and secs == sorted(secs)
    assert {n for n, _ in HORIZONS} == {"close", "t1h", "t6h", "t24h"}
