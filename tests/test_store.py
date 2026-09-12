"""Tests for the census store: idempotency, the reconciliation identity, resume equality.

Everything here protects one number. The coverage chart that gates the project
is `priced / scheduled`, and it goes wrong silently: a game in neither table, a
game in both, or a numerator row with no denominator row. Those three are the
tests that matter; the rest is bookkeeping.
"""

from __future__ import annotations

import json

import pytest

from chira.store import Store


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
            "INSERT INTO misses VALUES ('nba','2024-25','g1','no_market','[]',NULL)")
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
