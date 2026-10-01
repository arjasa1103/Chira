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
    marker_on_remote,
    open_holdout,
    read_marker,
)


def git(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True, check=True)
    return out.stdout


def _init_work(work):
    git(work, "init", "-q", "-b", "main")
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "T")
    (work / "model.py").write_text("# the frozen model\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "freeze the model")


@pytest.fixture
def repo(tmp_path):
    """A real git repo with one commit, clean, and PUSHED to a real remote.

    The seal requires the frozen commit to be public, so the fixture gives it
    a bare `origin` and pushes. Tests that need an unpushed HEAD make a new
    commit on top; `local_only_repo` has no remote at all.
    """
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    work.mkdir()
    _init_work(work)
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "-u", "origin", "main")
    return work


@pytest.fixture
def local_only_repo(tmp_path):
    """Clean and committed, but never pushed anywhere."""
    work = tmp_path / "local"
    work.mkdir()
    _init_work(work)
    return work


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

    def test_a_failed_commit_fails_closed(self, repo, con, monkeypatch):
        """If the commit fails, no label is returned, the marker stays on disk,
        and the next attempt refuses.

        This used to be tested with `commit=False`, a flag that SKIPPED the
        commit rather than failing it -- and that same flag was a free look at
        the holdout. Making git refuse the commit exercises the real path.
        """
        import chira.holdout as h

        real_git = h._git

        def git_that_refuses_commit(repo_, *args):
            if args and args[0] == "commit":
                raise HoldoutError("simulated: commit refused")
            return real_git(repo_, *args)

        monkeypatch.setattr(h, "_git", git_that_refuses_commit)
        with pytest.raises(HoldoutError, match="simulated"):
            open_holdout(con, reason="once", repo=repo)
        monkeypatch.setattr(h, "_git", real_git)

        assert (repo / MARKER).exists()
        assert not is_clean(repo)
        with pytest.raises(HoldoutError, match="already opened"):
            open_holdout(con, reason="again", repo=repo)


class TestNoFreeLook:
    """The bypass that shipped in b852666, pinned shut."""

    def test_there_is_no_commit_keyword(self, repo, con):
        with pytest.raises(TypeError):
            open_holdout(con, reason="peek", repo=repo, commit=False)  # type: ignore[call-arg]

    def test_deleting_the_marker_cannot_buy_a_second_look(self, repo, con):
        """The marker is always committed, so removing the file leaves the
        tree dirty (a tracked deletion) and the next open still refuses."""
        open_holdout(con, reason="once", repo=repo)
        (repo / MARKER).unlink()
        assert not is_clean(repo)
        with pytest.raises(HoldoutError):
            open_holdout(con, reason="again", repo=repo)


class TestTheFreezeMustBePublic:
    def test_an_unpushed_head_refuses(self, repo, con):
        (repo / "model.py").write_text("# tweaked after the push\n",
                                       encoding="utf-8")
        git(repo, "commit", "-q", "-am", "tweak")
        with pytest.raises(HoldoutError, match="not on the remote"):
            open_holdout(con, reason="week-9", repo=repo)
        assert not (repo / MARKER).exists()

    def test_a_repo_with_no_remote_refuses(self, local_only_repo, con):
        with pytest.raises(HoldoutError, match="not on the remote"):
            open_holdout(con, reason="week-9", repo=local_only_repo)
        assert not (local_only_repo / MARKER).exists()

    def test_a_pushed_head_opens(self, repo, con):
        assert open_holdout(con, reason="week-9", repo=repo)


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

    def test_a_row_with_no_season_is_refused(self):
        """`None` is not "2025-26", so the first version passed these. A guard
        that cannot see the column it guards must refuse, not approve."""
        with pytest.raises(HoldoutError, match="carry no season"):
            assert_dev_only([{"game_id": "x", "y": 1}])

    def test_an_empty_season_is_refused_too(self):
        with pytest.raises(HoldoutError, match="carry no season"):
            assert_dev_only([{"season": "", "game_id": "x"},
                             {"season": DEV_SEASON, "game_id": "d0"}])

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


class TestTheMarkerReachesTheRemote:
    """The residual bypass, closed 2026-10-01.

    A committed marker lives only in one clone. `git reset --hard HEAD~1`
    after an open removed it with no trace, `is_open` then saw nothing, and a
    second open returned the labels again. These pin the fix: the marker is
    pushed before any label comes out, and the remote copy is what is read.
    """

    def test_the_marker_is_on_the_remote_after_an_open(self, repo, con):
        open_holdout(con, reason="week-9 frozen model", repo=repo)
        assert marker_on_remote(repo) is True
        origin = repo.parent / "origin.git"
        assert MARKER in git(origin, "ls-tree", "--name-only", "main")

    def test_rewinding_the_marker_commit_no_longer_grants_a_second_look(
            self, repo, con):
        """The exact reproduction, now refused."""
        first = open_holdout(con, reason="the one pass", repo=repo)
        git(repo, "reset", "--hard", "HEAD~1")
        assert not (repo / MARKER).exists(), "the premise: locally gone"
        with pytest.raises(HoldoutError, match="on the remote"):
            open_holdout(con, reason="a second look", repo=repo)
        assert len(first) == 3

    def test_is_open_sees_the_remote_copy_after_a_rewind(self, repo, con):
        open_holdout(con, reason="the one pass", repo=repo)
        git(repo, "reset", "--hard", "HEAD~1")
        assert is_open(repo) is True

    def test_a_fresh_clone_of_the_branch_tip_refuses(self, repo, con, tmp_path):
        open_holdout(con, reason="the one pass", repo=repo)
        clone = tmp_path / "clone"
        git(tmp_path, "clone", "-q", str(repo.parent / "origin.git"), str(clone))
        git(clone, "config", "user.email", "t@example.com")
        git(clone, "config", "user.name", "T")
        with pytest.raises(HoldoutError, match="already opened"):
            open_holdout(con, reason="from a clone", repo=clone)

    def test_a_failed_push_releases_nothing_and_fails_closed(
            self, repo, con, monkeypatch):
        """The marker stays committed locally, so the next attempt refuses."""
        import chira.holdout as H
        real = H._git

        def refuse_push(repo_path, *args):
            if args and args[0] == "push":
                raise H.HoldoutError("push rejected by the test")
            return real(repo_path, *args)

        monkeypatch.setattr(H, "_git", refuse_push)
        with pytest.raises(HoldoutError, match="could NOT be pushed"):
            open_holdout(con, reason="week-9", repo=repo)
        monkeypatch.undo()
        assert (repo / MARKER).is_file(), "the local marker must survive"
        assert marker_on_remote(repo) is False
        with pytest.raises(HoldoutError, match="already opened"):
            open_holdout(con, reason="retry", repo=repo)

    def test_an_unconsultable_remote_raises_rather_than_reporting_closed(
            self, repo, con):
        """'Cannot tell' is not 'not opened'."""
        open_holdout(con, reason="the one pass", repo=repo)
        git(repo, "reset", "--hard", "HEAD~1")
        (repo.parent / "origin.git").rename(repo.parent / "origin.gone")
        with pytest.raises(HoldoutError):
            is_open(repo)

    def test_marker_on_remote_is_false_before_any_open(self, repo):
        assert marker_on_remote(repo) is False
