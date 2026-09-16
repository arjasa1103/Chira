"""The analysis frame's conventions, and the binning/bootstrap machinery.

These run against an in-memory DuckDB carrying the snapshot's view names, not
against the real snapshot: `data/` is gitignored, so a test that depended on it
would pass here and fail on a clean clone.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pytest

from chira.analysis import (
    LOOKS,
    assert_canonical,
    coverage_by_week,
    frame,
    look,
    look_coverage,
    price_pool,
    sport_seasons,
)
from chira.calibration import (
    MIN_BIN_GAMES,
    binned_curve,
    bootstrap_curve,
    bootstrap_scalars,
    n_bins_for,
    quantile_bin_edges,
)


def build(games, priced, misses=()):
    """An in-memory stand-in for `open_snapshot`'s views."""
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='UTC'")
    con.execute("""CREATE TABLE games (sport VARCHAR, season VARCHAR, game_id VARCHAR,
                   et_date DATE, winner VARCHAR)""")
    con.execute("""CREATE TABLE priced (sport VARCHAR, season VARCHAR, game_id VARCHAR,
                   p_home_close DOUBLE, p_home_t1h DOUBLE, p_home_t6h DOUBLE,
                   p_home_t24h DOUBLE, p_home_close_gamma DOUBLE, volume DOUBLE,
                   stale_flat_run BOOLEAN, cutoff_source VARCHAR,
                   gamma_delta_min INTEGER, secs_before_tip INTEGER,
                   convention VARCHAR, market_type VARCHAR)""")
    con.execute("""CREATE TABLE misses (sport VARCHAR, season VARCHAR,
                   game_id VARCHAR, reason VARCHAR)""")
    # Each guarded: DuckDB's executemany rejects an empty parameter list, and a
    # season with no priced game (or no miss) is a case these tests exercise.
    if games:
        con.executemany("INSERT INTO games VALUES (?,?,?,?,?)", games)
    if priced:
        con.executemany(f"INSERT INTO priced VALUES ({','.join('?' * 15)})", priced)
    if misses:
        con.executemany("INSERT INTO misses VALUES (?,?,?,?)", misses)
    return con


def g(gid, date, winner="home", sport="nba", season="2024-25"):
    return (sport, season, gid, date, winner)


def pr(gid, p=0.6, *, t1h=None, t6h=None, t24h=None, volume=1000.0,
       sport="nba", season="2024-25"):
    return (sport, season, gid, p, t1h if t1h is not None else p,
            t6h, t24h, p, volume, False, "league", 0, 60, "et", "moneyline")


class TestFrameConventions:
    def test_label_comes_from_the_league_not_the_market(self):
        con = build([g("1", "2024-10-22", "home"), g("2", "2024-10-22", "away")],
                    [pr("1"), pr("2")])
        f = frame(con)
        assert list(f["y"]) == [1.0, 0.0]

    def test_rows_are_canonically_ordered_even_if_inserted_backwards(self):
        """Binning ties depends on row order, so order is a correctness property."""
        con = build([g("9", "2024-10-22"), g("3", "2024-10-22"), g("7", "2024-10-22")],
                    [pr("9"), pr("3"), pr("7")])
        f = frame(con)
        assert list(f["game_id"]) == ["3", "7", "9"]
        assert_canonical(f)

    def test_assert_canonical_rejects_a_shuffled_frame(self):
        con = build([g("1", "2024-10-22"), g("2", "2024-10-22")], [pr("1"), pr("2")])
        f = frame(con)
        f["game_id"] = np.array(["2", "1"], dtype=object)
        with pytest.raises(ValueError, match="canonical"):
            assert_canonical(f)

    def test_week_of_season_floors_and_starts_at_one(self):
        """Week 1 is days 0-6. A rounding cast would put day 4 in week 2."""
        con = build([g("1", "2024-10-22"), g("2", "2024-10-26"),
                     g("3", "2024-10-29"), g("4", "2024-11-05")],
                    [pr("1"), pr("2"), pr("3"), pr("4")])
        f = frame(con)
        assert list(f["week_of_season"]) == [1, 1, 2, 3]

    def test_missing_volume_becomes_nan_not_zero(self):
        """A $0 market and an absent volume field are different facts."""
        con = build([g("1", "2024-10-22")], [pr("1", volume=None)])
        f = frame(con)
        assert np.isnan(f["volume"][0])

    def test_empty_frame_raises_rather_than_returning_nothing(self):
        con = build([g("1", "2024-10-22")], [pr("1")])
        with pytest.raises(ValueError, match="empty frame"):
            frame(con, "nhl")

    def test_sport_seasons_lists_what_is_priced(self):
        con = build([g("1", "2024-10-22"), g("2", "2024-10-22", sport="nhl")],
                    [pr("1"), pr("2", sport="nhl")])
        assert sport_seasons(con) == [("nba", "2024-25"), ("nhl", "2024-25")]

    def test_price_pool_is_the_closing_prices(self):
        con = build([g("1", "2024-10-22"), g("2", "2024-10-22")],
                    [pr("1", 0.4), pr("2", 0.7)])
        assert sorted(price_pool(con)) == [0.4, 0.7]


class TestLooksAreNotOneSample:
    def test_a_look_drops_only_the_games_missing_it(self):
        con = build([g("1", "2024-10-22"), g("2", "2024-10-22")],
                    [pr("1", 0.6, t24h=0.55), pr("2", 0.7, t24h=None)])
        f = frame(con)
        p, y = look(f, "p_t24h")
        assert len(p) == 1 and p[0] == 0.55
        assert len(y) == 1

    def test_look_coverage_reports_the_missing_count(self):
        con = build([g("1", "2024-10-22"), g("2", "2024-10-22")],
                    [pr("1", 0.6, t24h=0.55), pr("2", 0.7, t24h=None)])
        cov = look_coverage(frame(con))
        assert cov["p_t24h"] == {"available": 1, "missing": 1}
        assert cov["p_close"] == {"available": 2, "missing": 0}

    def test_unknown_look_raises(self):
        con = build([g("1", "2024-10-22")], [pr("1")])
        with pytest.raises(ValueError, match="unknown look"):
            look(frame(con), "p_t12h")

    def test_looks_constant_matches_the_frame(self):
        con = build([g("1", "2024-10-22")], [pr("1")])
        f = frame(con)
        assert all(name in f for name in LOOKS)


class TestCoverageByWeek:
    def test_scheduled_splits_into_priced_and_missed(self):
        con = build([g("1", "2024-10-22"), g("2", "2024-10-23"), g("3", "2024-10-30")],
                    [pr("1"), pr("2")],
                    [("nba", "2024-25", "3", "no_market")])
        weeks = coverage_by_week(con, "nba", "2024-25")
        assert [(w["week"], w["priced"], w["missed"], w["scheduled"]) for w in weeks] == [
            (1, 2, 0, 2), (2, 0, 1, 1)]

    def test_a_game_in_neither_table_breaks_the_identity_loudly(self):
        """The failure the misses table exists to prevent: a lost denominator."""
        con = build([g("1", "2024-10-22"), g("2", "2024-10-22")], [pr("1")])
        with pytest.raises(ValueError, match="reconciliation identity"):
            coverage_by_week(con, "nba", "2024-25")

    def test_volume_missing_is_counted_separately_from_the_median(self):
        con = build([g("1", "2024-10-22"), g("2", "2024-10-23")],
                    [pr("1", volume=None), pr("2", volume=500.0)])
        week = coverage_by_week(con, "nba", "2024-25")[0]
        assert week["volume_missing"] == 1
        assert week["median_volume"] == 500.0

    def test_a_week_with_no_priced_game_has_no_median(self):
        con = build([g("1", "2024-10-22")], [], [("nba", "2024-25", "1", "no_market")])
        week = coverage_by_week(con, "nba", "2024-25")[0]
        assert week["median_volume"] is None
        assert week["priced"] == 0


class TestBinning:
    def test_bin_count_honours_the_150_game_floor(self):
        assert n_bins_for(1229) == 8
        assert n_bins_for(896) == 5
        assert n_bins_for(4661) == 10   # capped at MAX_BINS
        assert n_bins_for(MIN_BIN_GAMES) == 1
        assert n_bins_for(10) == 1      # never zero bins

    def test_zero_n_raises(self):
        with pytest.raises(ValueError):
            n_bins_for(0)

    def test_duplicate_edges_are_collapsed_under_heavy_ties(self):
        """2,047 of 4,661 census closes are carried forward; ties are the norm."""
        p = np.concatenate([np.full(400, 0.5), np.linspace(0.2, 0.8, 100)])
        edges = quantile_bin_edges(p, 10)
        assert len(edges) == len(np.unique(edges))

    def test_binned_curve_reports_realized_n_not_assumed_equal_counts(self):
        p = np.concatenate([np.full(300, 0.5), np.linspace(0.6, 0.9, 100)])
        y = (np.arange(400) % 2).astype(float)
        c = binned_curve(p, y, quantile_bin_edges(p, 4))
        assert c["n"].sum() == 400
        assert (c["n"] > 0).all()

    def test_every_game_lands_in_exactly_one_bin(self):
        rng = np.random.default_rng(0)
        p = rng.uniform(0.05, 0.95, 900)
        y = (rng.random(900) < p).astype(float)
        c = binned_curve(p, y, quantile_bin_edges(p, 6))
        assert c["n"].sum() == 900


class TestBootstrapResamplesGames:
    def test_bands_bracket_the_observed_rate(self):
        rng = np.random.default_rng(1)
        p = rng.uniform(0.1, 0.9, 1200)
        y = (rng.random(1200) < p).astype(float)
        edges = quantile_bin_edges(p, 8)
        c = binned_curve(p, y, edges)
        b = bootstrap_curve(p, y, edges, reps=200, seed=2)
        assert np.all(b["lo"] <= c["obs_rate"] + 1e-9)
        assert np.all(c["obs_rate"] - 1e-9 <= b["hi"])

    def test_bands_narrow_as_n_grows(self):
        """If they do not, the bootstrap is not measuring sampling error."""
        def width(n):
            rng = np.random.default_rng(4)
            p = rng.uniform(0.1, 0.9, n)
            y = (rng.random(n) < p).astype(float)
            edges = quantile_bin_edges(p, 5)
            b = bootstrap_curve(p, y, edges, reps=200, seed=1)
            return float(np.mean(b["hi"] - b["lo"]))
        assert width(2000) < width(400)

    def test_bootstrap_is_deterministic_for_a_fixed_seed(self):
        rng = np.random.default_rng(6)
        p = rng.uniform(0.1, 0.9, 500)
        y = (rng.random(500) < p).astype(float)
        a = bootstrap_scalars(p, y, reps=100, seed=9)
        b = bootstrap_scalars(p, y, reps=100, seed=9)
        assert a["slope"] == b["slope"] and a["ece"] == b["ece"]

    def test_cox_failures_are_counted_not_silently_dropped(self):
        """A band conditioned on convergence is a band that hides degeneracy."""
        rng = np.random.default_rng(8)
        p = rng.uniform(0.2, 0.8, 300)
        y = (rng.random(300) < p).astype(float)
        s = bootstrap_scalars(p, y, reps=50, seed=1)
        assert "cox_failures" in s and s["cox_failures"] >= 0

    def test_scalar_cis_contain_the_point_estimate(self):
        rng = np.random.default_rng(10)
        p = rng.uniform(0.1, 0.9, 1500)
        y = (rng.random(1500) < p).astype(float)
        s = bootstrap_scalars(p, y, reps=300, seed=5)
        assert s["slope"]["lo"] < 1.0 < s["slope"]["hi"]
        assert s["ece"]["lo"] <= s["ece"]["p50"] <= s["ece"]["hi"]
