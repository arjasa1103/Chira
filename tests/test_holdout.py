"""The sealed holdout (PREREGISTRATION section 6, Amendment 5e).

These run against real throwaway git repositories in `tmp_path`, never
against this one. A test that opened the project's own seal would be a test
that destroys the thing it is testing.
"""

from __future__ import annotations

import json
import subprocess

import duckdb
import pytest

from chira.holdout import (
    DEV_SEASON,
    HOLDOUT_SEASON,
    MARKER,
    HoldoutError,
    assert_dev_only,
    dev_labels,
    head_commit,
    is_clean,
    is_open,
    open_holdout,
    read_marker,
)


def git(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True, check=True)
    return out.stdout


@pytest.fixture
def repo(tmp_path):
    """A real git repo with one commit, clean."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "model.py").write_text("# the frozen model\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "freeze the model")
    return tmp_path


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute("""CREATE TABLE games (sport VARCHAR, season VARCHAR,
                 game_id VARCHAR, et_date DATE, away VARCHAR, home VARCHAR,
                 winner VARCHAR)""")
    rows = []
    for i in range(4):
        rows.append(("nba", DEV_SEASON, f"d{i}", "2025-01-01", "bos", "nyk",
                     "home" if i % 2 else "away"))
    for i in range(3):
        rows.append(("nba", HOLDOUT_SEASON, f"h{i}", "2026-01-01", "bos",
                     "nyk", "home" if i % 2 else "away"))
    c.executemany("INSERT INTO games VALUES (?,?,?,?,?,?,?)", rows)
    return c


class TestItOpensOnce:
    def test_a_clean_tree_opens_and_returns_the_holdout_labels(self, repo, con):
        rows = open_holdout(con, reason="week-9 frozen model", repo=repo)
        assert len(rows) == 3
        assert {r["season"] for r in rows} == {HOLDOUT_SEASON}
        assert [r["y"] for r in rows] == [0, 1, 0]

    def test_the_marker_records_the_frozen_commit_and_the_time(self, repo, con):
        frozen = head_commit(repo)
        open_holdout(con, reason="week-9 frozen model", repo=repo)
        m = read_marker(repo)
        assert m["commit"] == frozen
        assert m["holdout_season"] == HOLDOUT_SEASON
        assert m["reason"] == "week-9 frozen model"
        assert m["games"] == 3
        assert len(m["label_sha256"]) == 64
        assert m["opened_at"].endswith("+00:00")

    def test_the_marker_is_committed_so_the_break_is_in_git_history(self, repo, con):
        open_holdout(con, reason="week-9 frozen model", repo=repo)
        assert is_clean(repo), "the marker must be committed, not left dirty"
        assert MARKER in git(repo, "show", "--name-only", "--format=", "HEAD")
        assert "opened once" in git(repo, "log", "-1", "--format=%s")

    def test_a_second_call_refuses(self, repo, con):
        open_holdout(con, reason="first and only", repo=repo)
        with pytest.raises(HoldoutError, match="already opened"):
            open_holdout(con, reason="just one more look", repo=repo)

    def test_the_refusal_names_when_and_why_it_was_opened(self, repo, con):
        open_holdout(con, reason="week-9 frozen model", repo=repo)
        with pytest.raises(HoldoutError, match="week-9 frozen model"):
            open_holdout(con, reason="again", repo=repo)

    def test_is_open_reports_the_state(self, repo, con):
        assert is_open(repo) is False
        open_holdout(con, reason="once", repo=repo)
        assert is_open(repo) is True


class TestItRefuses:
    def test_a_dirty_tree(self, repo, con):
        (repo / "model.py").write_text("# edited after the freeze\n",
                                       encoding="utf-8")
        with pytest.raises(HoldoutError, match="dirty"):
            open_holdout(con, reason="week-9", repo=repo)
        assert not (repo / MARKER).exists()

    def test_an_untracked_file_counts_as_dirty(self, repo, con):
        """An untracked model script is exactly what would NOT be in the
        commit the marker records."""
        (repo / "scratch_model.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(HoldoutError, match="dirty"):
            open_holdout(con, reason="week-9", repo=repo)

    def test_a_missing_reason(self, repo, con):
        for bad in ("", "   ", None):
            with pytest.raises(HoldoutError, match="reason is required"):
                open_holdout(con, reason=bad, repo=repo)
        assert not (repo / MARKER).exists()

    def test_a_store_with_no_holdout_games(self, repo):
        c = duckdb.connect(":memory:")
        c.execute("""CREATE TABLE games (sport VARCHAR, season VARCHAR,
                     game_id VARCHAR, et_date DATE, away VARCHAR,
                     home VARCHAR, winner VARCHAR)""")
        c.execute("INSERT INTO games VALUES "
                  "('nba', '2024-25', 'd0', '2025-01-01', 'bos', 'nyk', 'home')")
        with pytest.raises(HoldoutError, match="Refusing to burn the seal"):
            open_holdout(c, reason="week-9", repo=repo)
        assert not (repo / MARKER).exists()

    def test_a_directory_that_is_not_a_git_repo(self, tmp_path, con):
        with pytest.raises(HoldoutError):
            open_holdout(con, reason="week-9", repo=tmp_path / "nope")

    def test_a_leftover_uncommitted_marker_fails_closed(self, repo, con):
        """If the commit ever fails, the marker is on disk and the tree is
        dirty. The next attempt must refuse, not succeed."""
        open_holdout(con, reason="once", repo=repo, commit=False)
        assert not is_clean(repo)
        with pytest.raises(HoldoutError, match="already opened"):
            open_holdout(con, reason="again", repo=repo)


class TestTheDevPathIsUnguarded:
    def test_dev_labels_need_no_marker_and_leave_none(self, repo, con):
        rows = dev_labels(con)
        assert len(rows) == 4
        assert {r["season"] for r in rows} == {DEV_SEASON}
        assert not (repo / MARKER).exists()

    def test_dev_labels_never_include_the_holdout(self, con):
        assert_dev_only(dev_labels(con))


class TestAssertDevOnly:
    def test_it_catches_a_frame_assembled_without_a_season_filter(self):
        rows = [{"season": DEV_SEASON, "game_id": "d0"},
                {"season": HOLDOUT_SEASON, "game_id": "h0"}]
        with pytest.raises(HoldoutError, match="sealed holdout"):
            assert_dev_only(rows)

    def test_it_names_the_count_and_the_first_offender(self):
        rows = [{"season": HOLDOUT_SEASON, "game_id": "h9"},
                {"season": HOLDOUT_SEASON, "game_id": "h1"}]
        with pytest.raises(HoldoutError, match=r"2 training rows.*first: h1"):
            assert_dev_only(rows)

    def test_it_passes_on_dev_only_rows(self):
        assert assert_dev_only([{"season": DEV_SEASON, "game_id": "d0"}]) is None

    def test_it_passes_on_an_empty_frame(self):
        assert assert_dev_only([]) is None

    def test_the_label_can_be_customised(self):
        with pytest.raises(HoldoutError, match="tuning rows"):
            assert_dev_only([{"season": HOLDOUT_SEASON, "game_id": "h0"}],
                            what="tuning rows")


def test_the_marker_is_valid_json_a_human_can_read(repo, con):
    open_holdout(con, reason="week-9 frozen model", repo=repo)
    text = (repo / MARKER).read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text)["holdout_season"] == HOLDOUT_SEASON


def test_this_repository_has_not_had_its_holdout_opened():
    """A canary on the real project: if this ever fails, either week 9
    happened or something opened the seal by accident."""
    from pathlib import Path
    assert not (Path(__file__).resolve().parent.parent / MARKER).exists()
