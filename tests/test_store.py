"""Tests for the census store: idempotency, the reconciliation identity, resume equality.

Everything here protects one number. The coverage chart that gates the project
is `priced / scheduled`, and it goes wrong silently: a game in neither table, a
game in both, or a numerator row with no denominator row. Those three are the
tests that matter; the rest is bookkeeping.
"""

from __future__ import annotations

import json

import pytest

from chira.store import SCHEMA_VERSION, Store


def game(gid="g1", **kw):
    base = {"game_id": gid, "et_date": "2025-01-15", "away": "lal", "home": "bos",
            "away_pts": 100, "home_pts": 101, "winner": "home"}
    return {**base, **kw}


def priced_row(**kw):
    base = {"slug": "nba-lal-bos-2025-01-15", "convention": "et",
            "p_home_close": 0.61, "n_pre_tipoff": 900, "secs_before_tip": 42,
            "label_agreement": "agree"}
    return {**base, **kw}


@pytest.fixture
def store():
    s = Store()
    yield s
    s.close()


@pytest.fixture
def seeded(store):
    store.put_games("nba", "2024-25", [game("g1"), game("g2"), game("g3")])
    return store


class TestIdempotency:
    def test_writing_the_same_game_twice_leaves_one_row(self, store):
        store.put_games("nba", "2024-25", [game("g1")])
        store.put_games("nba", "2024-25", [game("g1")])
        assert store.reconcile("nba", "2024-25")["scheduled"] == 1

    def test_writing_the_same_priced_game_twice_leaves_one_row(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        seeded.put_priced("nba", "2024-25", "g1", priced_row(p_home_close=0.7))
        rows = seeded.priced_rows("nba", "2024-25")
        assert len(rows) == 1 and rows[0]["p_home_close"] == 0.7

    def test_a_resumed_run_is_digest_identical_not_byte_identical(self, seeded):
        """E20: resume equality is defined on canonical content, with tolerance."""
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        seeded.put_miss("nba", "2024-25", "g2", "no_market", ["a", "b"])
        first = seeded.digest()
        # A resumed run re-fetches and rewrites the same games.
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        seeded.put_miss("nba", "2024-25", "g2", "no_market", ["b", "a"])
        assert seeded.digest() == first

    def test_the_digest_ignores_run_metadata(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        before = seeded.digest()
        seeded.start_run("run-1", {"anything": 1})
        seeded.finish_run("run-1")
        assert seeded.digest() == before

    def test_the_digest_notices_a_changed_price(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        before = seeded.digest()
        seeded.put_priced("nba", "2024-25", "g1", priced_row(p_home_close=0.62))
        assert seeded.digest() != before

    def test_the_digest_tolerance_ignores_float_noise_below_it(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row(p_home_close=0.61))
        before = seeded.digest(places=6)
        seeded.put_priced("nba", "2024-25", "g1",
                          priced_row(p_home_close=0.61 + 1e-12))
        assert seeded.digest(places=6) == before


class TestMutualExclusion:
    def test_pricing_a_missed_game_removes_the_miss(self, seeded):
        seeded.put_miss("nba", "2024-25", "g1", "no_market", ["a"])
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        r = seeded.reconcile("nba", "2024-25")
        assert (r["priced"], r["misses"]) == (1, 0)
        assert seeded.double_counted() == 0

    def test_missing_a_priced_game_removes_the_price(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        seeded.put_miss("nba", "2024-25", "g1", "label_disagreement", ["a"])
        r = seeded.reconcile("nba", "2024-25")
        assert (r["priced"], r["misses"]) == (0, 1)

    def test_a_game_in_both_tables_is_caught(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        # Bypass the mutual delete to simulate the bug the delete prevents.
        seeded.db.execute(
            "INSERT INTO misses (sport, season, game_id, reason, attempted) "
            "VALUES ('nba','2024-25','g1','no_market','[]')")
        assert seeded.double_counted() == 1
        with pytest.raises(AssertionError, match="BOTH"):
            seeded.assert_reconciled("nba", "2024-25", require_complete=False)


class TestReasonEnum:
    def test_an_unknown_reason_is_refused(self, seeded):
        with pytest.raises(ValueError, match="unknown miss reason"):
            seeded.put_miss("nba", "2024-25", "g1", "vibes", [])

    @pytest.mark.parametrize("reason", ["no_market", "label_disagreement",
                                        "postponed_or_split_resolution"])
    def test_enum_members_are_accepted(self, seeded, reason):
        seeded.put_miss("nba", "2024-25", "g1", reason, [])
        assert seeded.miss_reasons("nba", "2024-25") == {reason: 1}

    def test_attempted_slugs_are_stored_sorted_and_readable(self, seeded):
        seeded.put_miss("nba", "2024-25", "g1", "no_market", ["z-slug", "a-slug"])
        row = seeded.db.execute("SELECT attempted FROM misses").fetchone()[0]
        assert json.loads(row) == ["a-slug", "z-slug"]

    def test_a_priced_row_missing_a_required_field_is_refused(self, seeded):
        bad = priced_row()
        del bad["label_agreement"]
        with pytest.raises(ValueError, match="label_agreement"):
            seeded.put_priced("nba", "2024-25", "g1", bad)


class TestReconciliation:
    def test_a_full_pass_balances(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        seeded.put_miss("nba", "2024-25", "g2", "no_market", [])
        seeded.put_miss("nba", "2024-25", "g3", "no_pre_tipoff_points", [])
        r = seeded.assert_reconciled("nba", "2024-25")
        assert r["balanced"] and r["pending"] == 0

    def test_a_partial_pass_fails_the_complete_check_and_passes_the_partial_one(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        with pytest.raises(AssertionError, match="reconciliation failed"):
            seeded.assert_reconciled("nba", "2024-25")
        assert seeded.assert_reconciled("nba", "2024-25", require_complete=False)

    def test_an_orphan_row_is_caught_even_though_the_counts_balance(self, store):
        """N missing denominator rows and N orphan numerator rows cancel out."""
        store.put_games("nba", "2024-25", [game("g1")])
        store.put_priced("nba", "2024-25", "ORPHAN", priced_row())
        assert store.reconcile("nba", "2024-25")["pending"] == 0
        assert store.orphans() == 1
        with pytest.raises(AssertionError, match="no scheduled game"):
            store.assert_reconciled("nba", "2024-25")

    def test_scoping_by_sport_does_not_mix_leagues(self, store):
        store.put_games("nba", "2024-25", [game("g1")])
        store.put_games("nhl", "2024-25", [game("h1")])
        store.put_priced("nba", "2024-25", "g1", priced_row())
        assert store.reconcile("nba", "2024-25")["priced"] == 1
        assert store.reconcile("nhl", "2024-25")["priced"] == 0


class TestResume:
    def test_settled_ids_cover_both_tables(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        seeded.put_miss("nba", "2024-25", "g2", "no_market", [])
        assert seeded.settled_game_ids("nba", "2024-25") == {"g1", "g2"}

    def test_settled_ids_are_scoped_to_the_season(self, store):
        store.put_games("nba", "2024-25", [game("g1")])
        store.put_games("nba", "2025-26", [game("g1")])
        store.put_priced("nba", "2024-25", "g1", priced_row())
        assert store.settled_game_ids("nba", "2025-26") == set()


class TestSchemaMigration:
    """CREATE TABLE IF NOT EXISTS made the store immutable once it existed."""

    def test_a_fresh_store_is_stamped_at_the_current_version(self, store):
        assert store.schema_version == SCHEMA_VERSION

    def test_an_unstamped_existing_store_is_migrated_not_ignored(self, tmp_path):
        """Simulates a week-2 store: tables exist, no meta row, no run_id column."""
        import duckdb
        path = tmp_path / "old.duckdb"
        con = duckdb.connect(str(path))
        con.execute("CREATE TABLE games (sport TEXT, season TEXT, game_id TEXT, "
                    "et_date DATE, away TEXT, home TEXT, away_pts INTEGER, "
                    "home_pts INTEGER, winner TEXT, neutral_site BOOLEAN, "
                    "PRIMARY KEY (sport, season, game_id))")
        con.execute("INSERT INTO games VALUES "
                    "('nba','2024-25','g1','2025-01-15','lal','bos',1,2,'home',FALSE)")
        con.close()

        with Store(path) as s:
            assert s.schema_version == SCHEMA_VERSION
            cols = [r[0] for r in s.db.execute("DESCRIBE games").fetchall()]
            assert "run_id" in cols, "the migration did not run"
            assert s.reconcile("nba", "2024-25")["scheduled"] == 1, "data was lost"

    def test_reopening_is_idempotent(self, tmp_path):
        path = tmp_path / "c.duckdb"
        with Store(path) as s:
            s.put_games("nba", "2024-25", [game("g1")])
            first = s.digest()
        with Store(path) as s:
            assert s.schema_version == SCHEMA_VERSION and s.digest() == first


class TestProvenance:
    def test_rows_carry_the_run_that_wrote_them(self, seeded):
        seeded.start_run("run-a", {})
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        seeded.put_miss("nba", "2024-25", "g2", "no_market", [])
        assert seeded.priced_rows("nba", "2024-25")[0]["run_id"] == "run-a"
        assert seeded.db.execute(
            "SELECT run_id FROM misses").fetchone()[0] == "run-a"

    def test_a_resumed_census_is_labelled_by_run_not_blended(self, seeded):
        seeded.start_run("run-a", {})
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        seeded.start_run("run-b", {})
        seeded.put_priced("nba", "2024-25", "g2", priced_row())
        runs = dict(seeded.db.execute(
            "SELECT game_id, run_id FROM priced").fetchall())
        assert runs == {"g1": "run-a", "g2": "run-b"}

    def test_rows_written_outside_a_run_are_null_not_mislabelled(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        assert seeded.priced_rows("nba", "2024-25")[0]["run_id"] is None


class TestPersistence:
    def test_a_store_on_disk_survives_reopening(self, tmp_path):
        path = tmp_path / "nested" / "census.duckdb"
        with Store(path) as s:
            s.put_games("nba", "2024-25", [game("g1")])
            s.put_priced("nba", "2024-25", "g1", priced_row())
            digest = s.digest()
        with Store(path) as s2:
            assert s2.digest() == digest
            assert s2.reconcile("nba", "2024-25")["priced"] == 1

    def test_a_timestamp_column_reads_back_without_pytz(self, seeded):
        """DuckDB converts TIMESTAMPTZ via pytz, which is not a dependency."""
        seeded.put_priced("nba", "2024-25", "g1",
                          priced_row(game_start_time="2025-01-16 00:30:00+00"))
        row = seeded.priced_rows("nba", "2024-25")[0]
        assert row["game_start_time"].startswith("2025-01-16")
        assert isinstance(seeded.digest(), str)

    def test_timestamps_render_in_utc_not_the_host_zone(self, seeded):
        """Caught by this test, not by review.

        DuckDB renders TIMESTAMPTZ in its SESSION zone, read from the OS rather
        than from TZ. Unpinned, the same row read back as "2025-01-15
        20:30:00-04" here, which would make `digest()` differ between machines
        and break resume equality across hosts.
        """
        seeded.put_priced("nba", "2024-25", "g1",
                          priced_row(game_start_time="2025-01-16 00:30:00+00"))
        rendered = seeded.priced_rows("nba", "2024-25")[0]["game_start_time"]
        assert rendered.endswith("+00"), rendered
        assert seeded.db.execute("SELECT current_setting('TimeZone')").fetchone()[0] == "UTC"


class FlakyDB:
    """Delegates to a real connection but raises on one SQL prefix.

    A wrapper rather than a monkeypatch: DuckDB's `execute` is a read-only C
    attribute, so it cannot be patched in place.
    """

    def __init__(self, real, fail_prefix):
        self._real = real
        self._fail_prefix = fail_prefix
        self.failures = 0

    def execute(self, sql, *a, **k):
        if sql.startswith(self._fail_prefix):
            self.failures += 1
            raise RuntimeError("disk went away")
        return self._real.execute(sql, *a, **k)

    def executemany(self, sql, *a, **k):
        return self._real.executemany(sql, *a, **k)


class TestTransactionSafety:
    def test_a_failed_priced_write_leaves_the_miss_row_intact(self, seeded):
        """The mutual delete and the insert are one transaction.

        If the insert succeeded and the delete then failed -- or vice versa --
        the game would be in both tables or in neither, which is exactly what
        the reconciliation identity is there to forbid.
        """
        seeded.put_miss("nba", "2024-25", "g1", "no_market", ["s"])
        real = seeded.db
        flaky = FlakyDB(real, "DELETE FROM misses")
        seeded.db = flaky
        with pytest.raises(RuntimeError, match="disk went away"):
            seeded.put_priced("nba", "2024-25", "g1", priced_row())
        seeded.db = real
        assert flaky.failures == 1
        r = seeded.reconcile("nba", "2024-25")
        assert (r["priced"], r["misses"]) == (0, 1), "the insert was not rolled back"

    def test_a_failed_miss_write_leaves_the_priced_row_intact(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        real = seeded.db
        seeded.db = FlakyDB(real, "DELETE FROM priced")
        with pytest.raises(RuntimeError):
            seeded.put_miss("nba", "2024-25", "g1", "no_market", ["s"])
        seeded.db = real
        r = seeded.reconcile("nba", "2024-25")
        assert (r["priced"], r["misses"]) == (1, 0)


class TestScoping:
    @pytest.fixture
    def two_sports(self, store):
        store.put_games("nba", "2024-25", [game("g1")])
        store.put_games("nhl", "2024-25", [game("h1")])
        store.put_games("nba", "2025-26", [game("g2")])
        store.put_priced("nba", "2024-25", "g1", priced_row())
        store.put_miss("nhl", "2024-25", "h1", "no_market", [])
        store.put_miss("nba", "2025-26", "g2", "no_pre_tipoff_points", [])
        return store

    def test_reconcile_over_everything(self, two_sports):
        r = two_sports.reconcile()
        assert (r["scheduled"], r["priced"], r["misses"]) == (3, 1, 2)

    def test_reconcile_by_season_across_sports(self, two_sports):
        r = two_sports.reconcile(season="2024-25")
        assert (r["scheduled"], r["priced"], r["misses"]) == (2, 1, 1)

    def test_reconcile_by_sport_across_seasons(self, two_sports):
        r = two_sports.reconcile("nba")
        assert (r["scheduled"], r["priced"], r["misses"]) == (2, 1, 1)

    def test_miss_reasons_unfiltered_and_by_sport(self, two_sports):
        assert two_sports.miss_reasons() == {"no_market": 1, "no_pre_tipoff_points": 1}
        assert two_sports.miss_reasons("nba") == {"no_pre_tipoff_points": 1}

    def test_label_agreement_unfiltered_and_by_sport(self, two_sports):
        assert two_sports.label_agreement() == {"agree": 1}
        assert two_sports.label_agreement("nhl") == {}

    def test_priced_rows_unfiltered_and_by_sport(self, two_sports):
        assert len(two_sports.priced_rows()) == 1
        assert two_sports.priced_rows("nhl") == []

    def test_a_season_only_filter_is_honoured_not_ignored(self, two_sports):
        """priced_rows(season=...) used to return every season silently."""
        assert two_sports.priced_rows(season="2024-25")[0]["game_id"] == "g1"
        assert two_sports.priced_rows(season="2025-26") == []
        assert two_sports.miss_reasons(season="2025-26") == {"no_pre_tipoff_points": 1}
        assert two_sports.label_agreement(season="2024-25") == {"agree": 1}
        assert two_sports.label_agreement(season="2025-26") == {}


def pts(n=5, base=1_700_000_000, p0=0.5):
    return [{"t": base + 60 * i, "p": round(p0 + i * 0.001, 6)} for i in range(n)]


class TestPriceSeriesWrites:
    def test_a_priced_game_stores_both_sides(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row(),
                          points={"home": pts(5), "away": pts(4, p0=0.4)})
        summary = seeded.points_summary("nba", "2024-25")
        assert summary == {"rows": 9, "series": 2, "priced_missing_series": 0,
                           "orphan_series": 0}

    def test_the_unnest_zip_keeps_t_and_p_aligned(self, seeded):
        home = pts(50)
        seeded.put_priced("nba", "2024-25", "g1", priced_row(), points={"home": home})
        got = seeded.db.execute(
            "SELECT t, p FROM price_points WHERE side='home' ORDER BY t").fetchall()
        assert got == [(pt["t"], pt["p"]) for pt in home]

    def test_re_pricing_replaces_the_series_rather_than_appending(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row(), points={"home": pts(5)})
        seeded.put_priced("nba", "2024-25", "g1", priced_row(), points={"home": pts(3)})
        assert seeded.points_summary()["rows"] == 3

    def test_downgrading_to_a_miss_drops_the_series(self, seeded):
        """Otherwise the snapshot ships a raw series for a game it calls missed."""
        seeded.put_priced("nba", "2024-25", "g1", priced_row(), points={"home": pts(5)})
        seeded.put_miss("nba", "2024-25", "g1", "label_disagreement", ["s"])
        assert seeded.points_summary() == {"rows": 0, "series": 0,
                                           "priced_missing_series": 0,
                                           "orphan_series": 0}

    def test_a_priced_row_without_points_is_counted_as_missing_its_series(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row())
        assert seeded.points_summary()["priced_missing_series"] == 1

    def test_an_unknown_side_is_refused_and_nothing_is_written(self, seeded):
        with pytest.raises(ValueError, match="side"):
            seeded.put_priced("nba", "2024-25", "g1", priced_row(),
                              points={"over": pts(3)})
        assert seeded.reconcile("nba", "2024-25")["priced"] == 0
        assert seeded.points_summary()["rows"] == 0

    def test_a_failed_series_insert_rolls_back_the_priced_row(self, seeded):
        """Row and series are one transaction: a kill between them must not leave a
        priced game whose snapshot series is silently empty."""
        real = seeded.db
        seeded.db = FlakyDB(real, "INSERT INTO price_points")
        with pytest.raises(RuntimeError):
            seeded.put_priced("nba", "2024-25", "g1", priced_row(),
                              points={"home": pts(3)})
        seeded.db = real
        assert seeded.reconcile("nba", "2024-25")["priced"] == 0

    def test_the_series_carries_the_run_id(self, seeded):
        seeded.start_run("run-x", {})
        seeded.put_priced("nba", "2024-25", "g1", priced_row(), points={"home": pts(2)})
        assert {r[0] for r in seeded.db.execute(
            "SELECT DISTINCT run_id FROM price_points").fetchall()} == {"run-x"}

    def test_the_digest_sees_a_moved_price_point(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row(), points={"home": pts(5)})
        before = seeded.digest()
        seeded.db.execute("UPDATE price_points SET p = p + 0.01 WHERE t = 1700000120")
        assert seeded.digest() != before

    def test_the_digest_is_stable_when_the_same_series_is_rewritten(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1", priced_row(), points={"home": pts(5)})
        before = seeded.digest()
        seeded.put_priced("nba", "2024-25", "g1", priced_row(), points={"home": pts(5)})
        assert seeded.digest() == before

    def test_new_looks_round_trip(self, seeded):
        seeded.put_priced("nba", "2024-25", "g1",
                          priced_row(p_home_t6h=0.55, p_home_t24h=0.52))
        row = seeded.priced_rows("nba", "2024-25")[0]
        assert (row["p_home_t6h"], row["p_home_t24h"]) == (0.55, 0.52)


class TestMigrationToV3:
    def test_a_v2_store_gains_the_looks_and_the_series_table(self, tmp_path):
        import duckdb

        from chira.store import SCHEMA
        path = tmp_path / "v2.duckdb"
        con = duckdb.connect(str(path))
        v2_schema = (SCHEMA.read_text(encoding="utf-8")
                     .replace("    p_home_t6h       DOUBLE,\n", "")
                     .replace("    p_home_t24h      DOUBLE,\n", ""))
        v2_schema = v2_schema[:v2_schema.index("CREATE TABLE IF NOT EXISTS price_points")] \
            + v2_schema[v2_schema.index("CREATE TABLE IF NOT EXISTS runs"):]
        con.execute(v2_schema)
        con.execute("INSERT INTO meta VALUES ('schema_version', '2')")
        con.close()

        with Store(path) as s:
            assert s.schema_version == SCHEMA_VERSION
            cols = {r[0] for r in s.db.execute("DESCRIBE priced").fetchall()}
            assert {"p_home_t6h", "p_home_t24h"} <= cols
            s.put_games("nba", "2024-25", [game("g1")])
            s.put_priced("nba", "2024-25", "g1", priced_row(), points={"home": pts(2)})
            assert s.points_summary()["rows"] == 2


class TestMigrationToV4:
    def test_a_v3_store_gains_the_amendment_columns_and_keeps_its_rows(self, tmp_path):
        import duckdb

        from chira.store import SCHEMA
        path = tmp_path / "v3.duckdb"
        con = duckdb.connect(str(path))
        con.execute(SCHEMA.read_text(encoding="utf-8"))
        con.execute("ALTER TABLE games DROP COLUMN start_time_utc")
        for col in ("market_type", "market_question", "cutoff_source", "league_start_time",
                    "gamma_delta_min", "p_home_close_gamma"):
            con.execute(f"ALTER TABLE priced DROP COLUMN {col}")
        con.execute("INSERT INTO meta VALUES ('schema_version', '3')")
        con.execute("INSERT INTO games (sport, season, game_id, et_date, away, home, winner) "
                    "VALUES ('nba','2024-25','g1','2025-01-15','lal','bos','home')")
        con.close()
        with Store(path) as s:
            assert s.schema_version == SCHEMA_VERSION
            gcols = {r[0] for r in s.db.execute("DESCRIBE games").fetchall()}
            pcols = {r[0] for r in s.db.execute("DESCRIBE priced").fetchall()}
            assert "start_time_utc" in gcols
            assert {"market_type", "cutoff_source", "league_start_time", "gamma_delta_min",
                    "p_home_close_gamma"} <= pcols
            assert s.reconcile("nba", "2024-25")["scheduled"] == 1, "rows lost in migration"


class TestAmendmentColumns:
    def test_the_audit_columns_round_trip_and_render_in_utc(self, seeded):
        seeded.put_games("nba", "2024-25", [game("g1", start_time_utc="2025-01-16T00:30:00Z")])
        seeded.put_priced("nba", "2024-25", "g1", priced_row(
            market_type="moneyline", market_question="Lakers vs. Celtics",
            cutoff_source="league", league_start_time="2025-01-16T00:30:00Z",
            gamma_delta_min=360, p_home_close_gamma=0.99))
        row = seeded.priced_rows("nba", "2024-25")[0]
        assert (row["market_type"], row["cutoff_source"], row["gamma_delta_min"],
                row["p_home_close_gamma"]) == ("moneyline", "league", 360, 0.99)
        assert row["league_start_time"] == "2025-01-16 00:30:00+00"
        got = seeded.db.execute(
            "SELECT CAST(start_time_utc AS VARCHAR) FROM games WHERE game_id='g1'").fetchone()[0]
        assert got == "2025-01-16 00:30:00+00"
