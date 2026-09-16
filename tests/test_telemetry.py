"""Tests for the run log and manifest.

The JSONL log is the only record of a multi-day census after the fact, and the
line that matters most is the one written immediately before a crash. So the
two things tested hardest are: every line is flushed, and the manifest ties the
data to the code that produced it.
"""

from __future__ import annotations

import json

import pytest

from chira.telemetry import Telemetry, git_hash, run_id


class TestRunId:
    def test_it_carries_a_prefix_and_is_unique_enough_to_sort(self):
        rid = run_id("census-nba")
        assert rid.startswith("census-nba-")
        assert "Z-" in rid, "the timestamp has to be in the id, and in UTC"

    def test_two_ids_from_the_same_process_share_the_pid_suffix(self):
        assert run_id().split("-")[-1] == run_id().split("-")[-1]


class TestManifest:
    def test_it_records_the_code_version_and_the_caller_fields(self):
        t = Telemetry(None, "r1", {"sport": "nba", "season": "2024-25"})
        assert t.manifest["run_id"] == "r1"
        assert t.manifest["sport"] == "nba"
        assert t.manifest["git_hash"]
        assert t.manifest["started_at"].endswith("Z")
        assert "cache_schema_version" in t.manifest

    def test_git_hash_never_raises(self, monkeypatch):
        """A census run must not die because git is missing."""
        import subprocess
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
        assert git_hash() == "unknown"


class TestCounting:
    def test_events_are_counted_even_with_no_file(self):
        t = Telemetry(None, "r1", {})
        t.event("game", outcome="priced")
        t.event("game", outcome="miss")
        t.event("reprobe_end")
        assert t.counts == {"game": 2, "reprobe_end": 1}

    def test_close_returns_the_counts(self):
        t = Telemetry(None, "r1", {})
        t.event("game")
        counts = t.close(priced=1)
        assert counts["game"] == 1 and counts["run_end"] == 1


class TestFileWriting:
    @pytest.fixture
    def path(self, tmp_path):
        return tmp_path / "nested" / "census.jsonl"

    def test_the_directory_is_created_and_a_run_start_line_is_written(self, path):
        t = Telemetry(path, "r1", {"sport": "nba"})
        lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
        assert len(lines) == 1
        assert lines[0]["kind"] == "run_start" and lines[0]["sport"] == "nba"
        t.close()

    def test_every_line_is_flushed_immediately(self, path):
        """Not on close: the interesting line is the one before the crash."""
        t = Telemetry(path, "r1", {})
        t.event("game", game_id="g1")
        assert "g1" in path.read_text(encoding="utf-8"), "line not visible before close"
        t.close()

    def test_each_line_carries_the_run_id_and_a_timestamp(self, path):
        t = Telemetry(path, "r1", {})
        t.event("game", game_id="g1")
        t.close()
        for raw in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(raw)
            assert row["run_id"] == "r1" and isinstance(row["ts"], float)

    def test_unserializable_values_do_not_kill_the_run(self, path):
        class Weird:
            def __repr__(self):
                return "<weird>"

        t = Telemetry(path, "r1", {})
        t.event("game", thing=Weird())
        t.close()
        assert "<weird>" in path.read_text(encoding="utf-8")

    def test_appending_does_not_truncate_an_earlier_run(self, path):
        Telemetry(path, "r1", {}).close()
        Telemetry(path, "r2", {}).close()
        ids = {json.loads(x)["run_id"] for x in path.read_text(encoding="utf-8").splitlines()}
        assert ids == {"r1", "r2"}

    def test_close_is_idempotent(self, path):
        t = Telemetry(path, "r1", {})
        t.close()
        t.close()  # must not raise on a closed handle
        assert path.read_text(encoding="utf-8").count('"run_end"') == 1
