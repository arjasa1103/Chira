"""The sealed holdout, opened by code, exactly once (Amendment 5e).

PREREGISTRATION section 6 seals the **2025-26 season** and opens it once,
after the model is frozen by commit. Amendment 5e turns that from an
intention into a mechanism: *"2025-26 labels reach the model only through a
single function that refuses a dirty tree, refuses a second call, and commits
a marker with the frozen commit hash and time."*

`open_holdout` is that function. There is no second one, and no keyword that
relaxes it.

**What the clean-tree check is actually for.** "The model is frozen by commit"
is not checkable by inspecting a model; what is checkable is that the working
tree matches a commit, and that the commit hash goes into the marker before
any label is returned. Whatever is committed at that instant IS the frozen
model, and git history is the proof of order -- the same argument Amendment
5b uses for the Elo constants.

**It fails closed.** The marker is written and committed BEFORE the labels are
returned. If the commit fails, the function raises and the caller gets
nothing; the half-written marker then leaves the tree dirty, so the next call
refuses on the dirty-tree check rather than quietly succeeding.

**What is NOT sealed.** The seal is on the MODEL's access to 2025-26 outcomes.
The census, the validation gate and headline 2 read both seasons by design:
headline 2 is a measurement of the market's own calibration, pre-registered in
section 8 to stratify *within* season, and it was published in week 6 before
any model existed. Confusing the two would either void a published result or
give a false sense that the model is sealed when it is not. `assert_dev_only`
is the guard for the model side.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

# PREREGISTRATION section 6.
HOLDOUT_SEASON = "2025-26"
DEV_SEASON = "2024-25"

# Committed at the repo root, deliberately conspicuous. Its presence in git
# history is the record that the seal was broken, and when.
MARKER = "HOLDOUT_OPENED.json"

_LABELS_SQL = """
SELECT sport, season, game_id, et_date, away, home,
       CASE WHEN winner = 'home' THEN 1 ELSE 0 END AS y
FROM games
WHERE season = ?
ORDER BY sport, season, game_id
"""


class HoldoutError(RuntimeError):
    """The seal refused. Never caught inside this module."""


def _git(repo: Path, *args: str) -> str:
    """Run git in `repo`. A list, never a shell string, so paths with spaces
    and Windows drive letters are not a quoting problem."""
    try:
        out = subprocess.run(["git", "-C", str(repo), *args],
                             capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        raise HoldoutError("git is not on PATH; the seal cannot record the "
                           "frozen commit, so it refuses to open") from e
    if out.returncode != 0:
        raise HoldoutError(f"git {' '.join(args)} failed in {repo}: "
                           f"{(out.stderr or out.stdout).strip()[:300]}")
    return out.stdout


def head_commit(repo: str | Path = ".") -> str:
    return _git(Path(repo), "rev-parse", "HEAD").strip()


def is_clean(repo: str | Path = ".") -> bool:
    """True when the working tree has no changes, staged or unstaged.

    `--porcelain` covers untracked files too, which matters: an untracked
    model script is exactly the thing that would not be in the recorded
    commit.
    """
    return not _git(Path(repo), "status", "--porcelain").strip()


def marker_path(repo: str | Path = ".") -> Path:
    return Path(repo) / MARKER


def is_open(repo: str | Path = ".") -> bool:
    """Has the holdout already been opened in this repository?"""
    return marker_path(repo).is_file()


def read_marker(repo: str | Path = ".") -> dict:
    p = marker_path(repo)
    if not p.is_file():
        raise HoldoutError(f"no {MARKER}: the holdout has not been opened")
    return json.loads(p.read_text(encoding="utf-8"))


def dev_labels(con) -> list[dict]:
    """The DEV season's labels. The normal path; no guard, no marker."""
    return _rows(con.execute(_LABELS_SQL, [DEV_SEASON]))


def assert_dev_only(rows, *, what: str = "training rows") -> None:
    """Raise if any row carries the holdout season.

    Model code calls this on whatever it is about to fit or tune on. It is
    cheap, and it catches the realistic failure -- a frame assembled without a
    season filter -- which no amount of care around `open_holdout` would.
    """
    bad = sorted({r["game_id"] for r in rows
                  if r.get("season") == HOLDOUT_SEASON})
    if bad:
        raise HoldoutError(
            f"{len(bad)} {what} are from the sealed holdout season "
            f"{HOLDOUT_SEASON} (first: {bad[0]}). The holdout is opened once, "
            f"by holdout.open_holdout, after the model is frozen.")


def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _digest(rows: list[dict]) -> str:
    """A stable hash of the released labels, so the marker pins WHAT was let
    out and not merely that something was."""
    payload = json.dumps(
        [[r["sport"], r["season"], r["game_id"], r["y"]] for r in rows],
        separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def open_holdout(con, *, reason: str, repo: str | Path = ".",
                 commit: bool = True) -> list[dict]:
    """Break the seal and return the 2025-26 labels. Once, ever.

    `reason` is required and goes into the marker: a sentence saying which
    frozen model this pass is for. `commit=False` exists only for tests and
    still writes the marker, so it cannot be used to take a free look.

    Raises `HoldoutError` if the tree is dirty, if the marker already exists,
    or if git is unavailable. Nothing is returned in any of those cases.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise HoldoutError("reason is required: the marker has to say which "
                           "frozen model this single pass was for")
    repo = Path(repo)
    if is_open(repo):
        prior = read_marker(repo)
        raise HoldoutError(
            f"the holdout was already opened at {prior.get('opened_at')} "
            f"on commit {str(prior.get('commit'))[:12]} "
            f"({prior.get('reason')!r}). It is opened ONCE. Reopening it "
            f"would make every number after it a second look, and deleting "
            f"{MARKER} to get around this is recorded in git history.")
    if not is_clean(repo):
        raise HoldoutError(
            "the working tree is dirty, so there is no commit that describes "
            "the model about to see the holdout. Commit or stash first; the "
            "marker records the hash and that record is the freeze.\n"
            + _git(repo, "status", "--short")[:600])

    frozen = head_commit(repo)
    rows = _rows(con.execute(_LABELS_SQL, [HOLDOUT_SEASON]))
    if not rows:
        raise HoldoutError(
            f"no {HOLDOUT_SEASON} games in this store. Refusing to burn the "
            f"seal on an empty read.")

    marker = {
        "holdout_season": HOLDOUT_SEASON,
        "opened_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "commit": frozen,
        "reason": reason.strip(),
        "games": len(rows),
        "label_sha256": _digest(rows),
        "note": ("Written by chira.holdout.open_holdout. Its presence is what "
                 "makes a second call refuse. Do not delete it."),
    }
    marker_path(repo).write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if commit:
        # Before the labels are handed over, never after. A failure here
        # leaves the marker on disk and the tree dirty, so the next attempt
        # refuses rather than silently succeeding.
        _git(repo, "add", "--", MARKER)
        _git(repo, "commit", "-m",
             f"holdout: opened once on {frozen[:12]} -- {reason.strip()}",
             "-m", f"{len(rows)} {HOLDOUT_SEASON} labels released, "
                   f"sha256 {marker['label_sha256'][:16]}.")
    return rows
