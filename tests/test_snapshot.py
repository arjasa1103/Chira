"""Tests for the immutable census snapshot (T7).

The snapshot is what every later phase reads, so the tests are about the ways it
could be quietly wrong: cut from an unfinished census, edited after the fact,
overwritten, or unreadable without the network. conftest blocks sockets for
every test here, so a passing `open_snapshot` test IS the plan's "every
downstream phase runs with the network disabled" check.
"""

from __future__ import annotations

import json
import stat

import pytest

from chira.snapshot import (
    SnapshotError,
    create_snapshot,
    make_writable,
    open_snapshot,
    preflight,
    verify_snapshot,
)
from chira.store import Store


def game(gid, sport="nba", season="2024-25", **kw):
    return {"game_id": gid, "et_date": "2025-01-15", "away": "lal", "home": "bos",
            "away_pts": 100, "home_pts": 110, "winner": "home", **kw}


def row(**kw):
    return {"slug": "nba-lal-bos-2025-01-15", "convention": "et", "p_home_close": 0.61,
            "p_home_t1h": 0.60, "p_home_t6h": 0.58, "p_home_t24h": 0.55,
            "n_pre_tipoff": 3, "secs_before_tip": 40, "label_agreement": "agree",
            "market_winner": "home", "complement_ok": True, "complement_sum": 1.0,
            "volume": 312000.0, "game_start_time": "2025-01-16 00:30:00+00", **kw}


def series(n=3):
    home = [{"t": 1737000000 + 60 * i, "p": 0.60 + i * 0.001} for i in range(n)]
    away = [{"t": 1737000000 + 60 * i, "p": 0.40 - i * 0.001} for i in range(n)]
    return {"home": home, "away": away}


@pytest.fixture
def finished():
    """A complete census across two sport-seasons: every game priced or missed."""
    s = Store()
    s.start_run("run-1", {"sport": "both"})
    s.put_games("nba", "2024-25", [game("g1"), game("g2")])
    s.put_games("nhl", "2025-26", [game("h1", sport="nhl", season="2025-26")])
    s.put_priced("nba", "2024-25", "g1", row(), points=series())
    s.put_miss("nba", "2024-25", "g2", "no_market", ["a", "b"])
    s.put_priced("nhl", "2025-26", "h1", row(slug="nhl-lal-bos-2025-01-15"),
                 points=series(4))
    s.finish_run("run-1")
    yield s
    s.close()


@pytest.fixture
def snaproot(tmp_path):
    root = tmp_path / "snapshots"
    yield root
    if root.exists():
        make_writable(root)  # read-only snapshots would block pytest's cleanup


class TestPreflight:
    def test_a_finished_census_passes(self, finished):
        report = preflight(finished)
        assert set(report) == {"nba/2024-25", "nhl/2025-26"}
        assert report["nba/2024-25"]["balanced"]

    def test_an_unfinished_census_is_refused(self, finished):
        finished.put_games("nba", "2024-25", [game("g3")])
        with pytest.raises(SnapshotError, match="unfinished"):
            preflight(finished)

    def test_a_priced_game_without_its_series_is_refused(self, finished):
        finished.db.execute("DELETE FROM price_points WHERE game_id = 'g1'")
        with pytest.raises(SnapshotError, match="no raw series"):
            preflight(finished)

    def test_an_empty_store_is_refused(self):
        with pytest.raises(SnapshotError, match="no scheduled games"):
            preflight(Store())


class TestCreate:
    def test_every_table_is_written_with_matching_row_counts(self, finished, snaproot):
        path = create_snapshot(finished, snaproot)
        manifest = json.loads((path / "manifest.json").read_text())
        assert manifest["tables"]["games"]["rows"] == 3
        assert manifest["tables"]["priced"]["rows"] == 2
        assert manifest["tables"]["misses"]["rows"] == 1
        assert manifest["tables"]["price_points"]["rows"] == 6 + 8
        assert manifest["tables"]["price_points"]["partitions"] == {
            "nba/2024-25": 6, "nhl/2025-26": 8}
        assert manifest["store_digest"] == finished.digest()
        assert manifest["runs"] == ["run-1"]

    def test_the_directory_name_carries_the_store_digest(self, finished, snaproot):
        path = create_snapshot(finished, snaproot)
        assert path.name.endswith(finished.digest()[:12])

    def test_the_manifest_freezes_the_volume_definition(self, finished, snaproot):
        """PREREGISTRATION requires it: terminal volume is outcome-correlated."""
        manifest = json.loads((create_snapshot(finished, snaproot)
                               / "manifest.json").read_text())
        assert "outcome-correlated" in manifest["volume_definition"]

    def test_files_and_directories_are_read_only(self, finished, snaproot):
        path = create_snapshot(finished, snaproot)
        for p in path.rglob("*"):
            assert not p.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH), p

    def test_it_never_overwrites(self, finished, snaproot):
        create_snapshot(finished, snaproot)
        with pytest.raises(SnapshotError, match="immutable"):
            create_snapshot(finished, snaproot)

    def test_a_failed_snapshot_leaves_nothing_under_a_real_name(self, finished, snaproot,
                                                                monkeypatch):
        import chira.snapshot as snap
        monkeypatch.setattr(snap, "_sha256", lambda p: (_ for _ in ()).throw(OSError("disk")))
        with pytest.raises(OSError):
            create_snapshot(finished, snaproot)
        assert list(snaproot.iterdir()) == []


class TestReadBack:
    def test_the_snapshot_opens_offline_and_matches_the_store(self, finished, snaproot):
        """Sockets are blocked by conftest: this is the network-disabled check."""
        con = open_snapshot(create_snapshot(finished, snaproot))
        assert con.execute("SELECT count(*) FROM games").fetchone()[0] == 3
        assert con.execute(
            "SELECT count(*) FROM price_points WHERE sport='nhl' AND season='2025-26'"
        ).fetchone()[0] == 8
        got = con.execute("SELECT p_home_close, p_home_t24h FROM priced "
                          "WHERE game_id='g1'").fetchone()
        assert got == (0.61, 0.55)

    def test_timestamps_are_utc_text_whatever_the_reader_zone(self, finished, snaproot):
        con = open_snapshot(create_snapshot(finished, snaproot))
        con.execute("SET TimeZone='America/Los_Angeles'")
        gst = con.execute("SELECT game_start_time FROM priced WHERE game_id='g1'").fetchone()[0]
        assert gst == "2025-01-16T00:30:00+00:00"

    def test_partition_columns_come_back_as_text(self, finished, snaproot):
        """hive partitioning would otherwise type-infer '2024-25' however it likes."""
        con = open_snapshot(create_snapshot(finished, snaproot))
        assert con.execute("SELECT DISTINCT season FROM games ORDER BY 1").fetchall() == [
            ("2024-25",), ("2025-26",)]

    def test_the_raw_series_round_trips_exactly(self, finished, snaproot):
        con = open_snapshot(create_snapshot(finished, snaproot))
        got = con.execute("SELECT t, p FROM price_points WHERE game_id='g1' "
                          "AND side='home' ORDER BY t").fetchall()
        assert got == [(pt["t"], pt["p"]) for pt in series()["home"]]


class TestVerify:
    def test_a_clean_snapshot_verifies(self, finished, snaproot):
        path = create_snapshot(finished, snaproot)
        assert verify_snapshot(path)["snapshot_id"] == path.name

    def test_an_edited_file_is_caught(self, finished, snaproot):
        path = create_snapshot(finished, snaproot)
        make_writable(path)
        victim = next(path.glob("priced/**/*.parquet"))
        data = bytearray(victim.read_bytes())
        data[len(data) // 2] ^= 0xFF
        victim.write_bytes(bytes(data))
        with pytest.raises(SnapshotError, match="checksum"):
            verify_snapshot(path)
        with pytest.raises(SnapshotError):
            open_snapshot(path)

    def test_an_unlisted_file_is_caught(self, finished, snaproot):
        path = create_snapshot(finished, snaproot)
        make_writable(path)
        (path / "priced" / "sneaky.parquet").write_bytes(b"x")
        with pytest.raises(SnapshotError, match="extra"):
            verify_snapshot(path)

    def test_a_deleted_file_is_caught(self, finished, snaproot):
        path = create_snapshot(finished, snaproot)
        make_writable(path)
        next(path.glob("misses/**/*.parquet")).unlink()
        with pytest.raises(SnapshotError, match="missing"):
            verify_snapshot(path)

    def test_a_directory_with_no_manifest_is_refused(self, tmp_path):
        with pytest.raises(SnapshotError, match="manifest"):
            verify_snapshot(tmp_path)


def test_league_times_are_written_as_utc_text(snaproot):
    s = Store()
    s.put_games("nba", "2024-25", [game("g1", start_time_utc="2025-01-16T00:30:00Z")])
    s.put_priced("nba", "2024-25", "g1",
                 row(cutoff_source="league", league_start_time="2025-01-16T00:30:00Z"),
                 points=series())
    con = open_snapshot(create_snapshot(s, snaproot))
    con.execute("SET TimeZone='Asia/Tokyo'")
    got = con.execute("SELECT start_time_utc FROM games").fetchone()[0]
    assert got == "2025-01-16T00:30:00+00:00"
    assert con.execute("SELECT league_start_time, cutoff_source FROM priced").fetchone() == (
        "2025-01-16T00:30:00+00:00", "league")
    s.close()
