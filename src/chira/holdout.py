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

**One hole is NOT closed in code, and cannot be.** A force-push to the branch
can remove the pushed marker. Branch protection on `main` that blocks
force-pushes is a GitHub setting, not something this module can enforce; it is
the last link in the chain and it belongs to the repository owner.

**It fails closed, and it does not burn the seal on a network error.** The
marker is written, committed and pushed BEFORE the labels are returned, and
labels are released only once the marker is confirmed ON THE REMOTE -- the
remote's word, not the push's exit status. If the commit fails, the caller
gets nothing and the half-written marker leaves the tree dirty, so the next
call refuses. If the push fails and the marker is not on the remote, nothing
was released and nothing is on the record, so the local marker commit is
rolled back and a retry opens cleanly. The first version kept that commit and
told the caller to push it and re-run; the re-run then refused on the local
marker, so one Wi-Fi blip spent the holdout with no label ever released
(reproduced 2026-10-01).

**What is NOT sealed.** The seal is on the MODEL's access to 2025-26 outcomes.
The census, the validation gate and headline 2 read both seasons by design:
headline 2 is a measurement of the market's own calibration, pre-registered in
section 8 to stratify *within* season, and it was published in week 6 before
any model existed. Confusing the two would either void a published result or
give a false sense that the model is sealed when it is not. `assert_dev_only`
is the guard for the model side.

**Pre-game inputs built from EARLIER 2025-26 results are not labels either.**
The feature store's prior wins and win rates, and the Elo walk through 2025-26
(Amendment 5b), read the outcomes of games that were over before the game
being predicted started. That is what a point-in-time input is; every live
prediction works the same way. What keeps them honest is not this seal but
the availability rule (`features.RESULT_DELAY_SECONDS`) and the two canaries
that prove it: `TestTheLeakageCanary` in tests/test_features.py and
`TestTheRatingCanary` in tests/test_ratings.py. What this seal guards is
SCORING: a 2025-26 game's OWN outcome entering a fit, a tune or an evaluation
of any model, which happens only through `open_holdout`. This is why
`open_holdout` releases outcomes and not scores or start times, and why the
2025-26 rating walk reads the store directly. Written down 2026-10-01, before
week 9, because the feature table already held 2025-26 rows and nothing said
why that was allowed.
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


def _upstream(repo: Path) -> tuple[str, str, str]:
    """(full upstream ref, remote name, branch name) for HEAD's upstream."""
    ref = _git(repo, "rev-parse", "--abbrev-ref",
               "--symbolic-full-name", "@{u}").strip()
    remote, branch = ref.split("/", 1)
    return ref, remote, branch


def marker_on_remote(repo: str | Path = ".") -> bool:
    """Does the marker exist on the upstream branch, as the remote sees it?

    Fetches first. **This is the question that matters**, because the local
    file is deletable without a trace: `git reset --hard HEAD~1` after an open
    removes the marker commit, which exists only locally, and the next
    `open_holdout` used to succeed. Reproduced 2026-10-01 against the real
    module. The marker is pushed before any label is returned, so the remote
    is the copy that cannot be quietly rewound.

    Raises `HoldoutError` when the remote cannot be consulted at all -- no
    upstream, offline, fetch refused. The caller must treat that as "unknown"
    and refuse, never as "not opened".
    """
    repo = Path(repo)
    ref, remote, _ = _upstream(repo)
    _git(repo, "fetch", "--quiet", remote)
    rc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{ref}:{MARKER}"],
        capture_output=True, check=False).returncode
    return rc == 0


def is_open(repo: str | Path = ".") -> bool:
    """Has the holdout been opened, locally OR on the remote?

    Local first, because that answer needs no network. A missing local marker
    is NOT an answer on its own, so the remote is consulted too, and a remote
    that cannot be reached raises rather than returning False.
    """
    if marker_path(repo).is_file():
        return True
    return marker_on_remote(repo)


def read_marker(repo: str | Path = ".") -> dict:
    p = marker_path(repo)
    if not p.is_file():
        raise HoldoutError(f"no {MARKER}: the holdout has not been opened")
    return json.loads(p.read_text(encoding="utf-8"))


def dev_labels(con) -> list[dict]:
    """The DEV season's labels. The normal path; no guard, no marker."""
    return _rows(con.execute(_LABELS_SQL, [DEV_SEASON]))


def assert_dev_only(rows, *, what: str = "training rows") -> None:
    """Raise if any row carries the holdout season, OR carries no season at all.

    Model code calls this on whatever it is about to fit or tune on. It is
    cheap, and it catches the realistic failure -- a frame assembled without a
    season filter -- which no amount of care around `open_holdout` would.

    **A row with no `season` is refused, not passed.** The first version
    tested `r.get("season") == HOLDOUT_SEASON`, and `None` is not "2025-26",
    so a frame built without the column sailed through: a guard that cannot
    see the thing it guards passes by construction. Absent is not dev.
    """
    missing = sum(1 for r in rows if not r.get("season"))
    if missing:
        raise HoldoutError(
            f"{missing} {what} carry no season, so this guard cannot tell dev "
            f"from the sealed {HOLDOUT_SEASON}. Carry the season column through "
            f"to the frame being fitted; a missing season is not a dev season.")
    bad = sorted({r["game_id"] for r in rows
                  if r.get("season") == HOLDOUT_SEASON})
    if bad:
        raise HoldoutError(
            f"{len(bad)} {what} are from the sealed holdout season "
            f"{HOLDOUT_SEASON} (first: {bad[0]}). The holdout is opened once, "
            f"by holdout.open_holdout, after the model is frozen.")


def assert_scorable(rows, *, what: str = "rows", repo: str | Path = ".") -> None:
    """Raise if these rows may not be SCORED yet.

    Scoring means comparing a forecast against an outcome: a log loss, a
    Brier, a reliability bin, a Clark-West term. `assert_dev_only` guards
    what a model is FITTED on; this guards what it is MEASURED on, and they
    are different leaks. A pre-game rating for a 2025-26 game is a legitimate
    point-in-time feature (see the module docstring); the log loss of that
    rating against the 2025-26 result is a holdout score.

    **Why this exists as code and not as care.** On 2026-10-01
    `scripts/build_ratings.py` printed the Elo's log loss and Brier for
    2025-26 in a per-season summary table -- 0.69488 and 0.25065 for the NHL.
    The constants were already frozen and pushed, so the choice could not have
    been affected, but holdout performance was visible before the seal was
    broken, which is precisely what the seal is for. It was disclosed rather
    than quietly dropped, and the scoring path now refuses instead of relying
    on whoever writes the next summary table.

    Holdout rows become scorable once the seal is formally open, so there is
    no keyword to relax this: break the seal through `open_holdout` and the
    marker makes scoring legal. The check is the LOCAL marker only -- it runs
    inside scoring loops and must not touch the network; `open_holdout` is
    where the authoritative once-only check lives.
    """
    missing = sum(1 for r in rows if not r.get("season"))
    if missing:
        raise HoldoutError(
            f"{missing} {what} carry no season, so this guard cannot tell "
            f"whether scoring them is a holdout peek. Carry the season column "
            f"through to whatever is being scored; a missing season is not a "
            f"dev season.")
    held = sorted({r["game_id"] for r in rows
                   if r.get("season") == HOLDOUT_SEASON})
    if held and not marker_path(repo).is_file():
        raise HoldoutError(
            f"{len(held)} {what} are from the sealed holdout season "
            f"{HOLDOUT_SEASON} (first: {held[0]}), and the seal is not open. "
            f"Pre-game inputs from 2025-26 are features and are allowed; "
            f"SCORING a forecast against a 2025-26 outcome is not, until "
            f"holdout.open_holdout has been called and its marker committed.")


def is_pushed(repo: str | Path = ".") -> bool:
    """Is HEAD already on the upstream branch, as the remote sees it NOW?

    Fetches first, so a stale local `origin/main` cannot stand in for the
    remote. Any failure -- no upstream, offline, fetch refused -- is False,
    and False refuses the open: the seal fails closed on the network exactly
    as it does on git itself.
    """
    repo = Path(repo)
    try:
        upstream = _git(repo, "rev-parse", "--abbrev-ref",
                        "--symbolic-full-name", "@{u}").strip()
        _git(repo, "fetch", "--quiet", upstream.split("/", 1)[0])
    except HoldoutError:
        return False
    rc = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", "HEAD", upstream],
        capture_output=True, check=False).returncode
    return rc == 0


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


def open_holdout(con, *, reason: str, repo: str | Path = ".") -> list[dict]:
    """Break the seal and return the 2025-26 labels. Once, ever.

    `reason` is required and goes into the marker: a sentence saying which
    frozen model this pass is for.

    **There is no `commit=False`.** An earlier version had one, "only for
    tests", and it was a free look: the marker was written but never
    committed, so deleting the untracked file left no trace and a second call
    succeeded. Demonstrated 2026-09-28 in a throwaway repo -- two looks, one on
    the record, nothing in git history. Every open now commits.

    **The frozen model must already be public.** HEAD has to be on the
    upstream branch as the remote sees it after a fetch. An unpushed "frozen"
    commit can be amended after a peek, and the reflog that would betray it is
    local and expires. For a project whose rule is that the git hash is the
    timestamp, a freeze only the author can see is not a freeze.

    **The marker is pushed before any label is returned.** A local commit was
    not enough: `git reset --hard HEAD~1` after an open removed the marker
    commit and a second call succeeded, with nothing on the remote to show it
    (reproduced 2026-10-01). `marker_on_remote` now reads the pushed copy, and
    a push that fails releases no labels.

    **A push that does not land does not spend the seal.** Labels are released
    only once the marker is confirmed on the remote. If it is not there, the
    local marker commit is rolled back and the call raises; a retry opens
    cleanly. If the remote cannot be checked at all, the marker stays and the
    call raises; a re-run resolves it either way.

    Raises `HoldoutError` if the reason is empty, the marker already exists
    on the record (locally or on the remote), the remote cannot be consulted,
    the tree is dirty, HEAD is not on the remote, the store has no holdout
    games, the push does not land, or git is unavailable. Nothing is returned
    in any of those cases.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise HoldoutError("reason is required: the marker has to say which "
                           "frozen model this single pass was for")
    repo = Path(repo)
    # The local marker first: the most specific message. One local marker is
    # NOT a refusal: an open whose push never reached the remote left its
    # marker commit here with no label released and nothing on the record.
    # That one is rolled back and the open proceeds; every other is refused.
    if marker_path(repo).is_file() and _is_stranded(repo):
        _roll_back_marker(repo)
    if marker_path(repo).is_file():
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

    if not is_pushed(repo):
        raise HoldoutError(
            "HEAD is not on the remote, so the model about to see the holdout "
            "is frozen only on this machine. Push it first; the marker records "
            "a hash anyone can check was public before a label came out.")

    # AFTER is_pushed, which establishes that an upstream exists and can be
    # reached. Checking the remote marker first made a repo with no remote
    # report a raw `@{u}` git error instead of "HEAD is not on the remote".
    if marker_on_remote(repo):
        raise HoldoutError(
            f"{MARKER} is on the remote but not in this working tree, so the "
            f"holdout was opened and the marker commit has been rewound or "
            f"this is a fresh clone of an older commit. It is opened ONCE. "
            f"Fetch and reset to the branch tip to see the record.")

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

    # Commit AND PUSH before the labels are handed over, never after.
    #
    # The commit alone was not enough: it lives only in this clone, and
    # `git reset --hard HEAD~1` removes it without a trace, after which the
    # old `is_open` saw no marker and a second open succeeded. Pushing puts
    # the record somewhere a local rewind cannot reach, and `marker_on_remote`
    # is what reads it back.
    _git(repo, "add", "--", MARKER)
    _git(repo, "commit", "-m",
         f"holdout: opened once on {frozen[:12]} -- {reason.strip()}",
         "-m", f"{len(rows)} {HOLDOUT_SEASON} labels released, "
               f"sha256 {marker['label_sha256'][:16]}.")
    _, remote, branch = _upstream(repo)
    push_error: HoldoutError | None = None
    try:
        _git(repo, "push", "--quiet", remote, f"HEAD:refs/heads/{branch}")
    except HoldoutError as e:
        push_error = e

    # Release on the REMOTE's word, not the push's exit status. A push can
    # report failure after the server accepted it; then the record is public
    # and the labels are owed. And a push that did not land must not spend the
    # seal: nothing was released, so the local commit is rolled back.
    try:
        published = marker_on_remote(repo)
    except HoldoutError as e:
        raise HoldoutError(
            f"the marker is committed locally, and whether it reached the "
            f"remote cannot be checked ({e}). No label is released. Do not "
            f"delete {MARKER}. Re-run once the remote is reachable: if the "
            f"record never became public, the marker commit is rolled back and "
            f"the open proceeds; if it did, the open is on the record and is "
            f"refused as already opened.") from (push_error or e)
    if not published:
        _roll_back_marker(repo)
        raise HoldoutError(
            f"the marker could not be pushed ({push_error}), so no label was "
            f"released and nothing is on the record. The local marker commit "
            f"was rolled back; the holdout is still sealed and a retry opens "
            f"it cleanly.") from push_error
    return rows


def _is_stranded(repo: Path) -> bool:
    """Is the local marker an open that never reached the remote?

    True only when ALL hold: HEAD is the commit that added the marker, its
    parent is the frozen commit the marker names, the tree is otherwise clean,
    and the remote -- consulted, not assumed -- does not have it. Labels are
    released only after the remote confirms, so such a marker released none.
    A remote that cannot be reached RAISES, as everywhere else in the seal.
    """
    try:
        added = _git(repo, "diff-tree", "--no-commit-id", "--name-only",
                     "-r", "HEAD").split()
        parent = _git(repo, "rev-parse", "HEAD~1").strip()
    except HoldoutError:
        return False
    if MARKER not in added or parent != read_marker(repo).get("commit"):
        return False
    if not is_clean(repo):
        return False
    return not marker_on_remote(repo)


def _roll_back_marker(repo: Path) -> None:
    """Undo an unpublished marker commit. `--keep`, not `--hard`: it refuses
    rather than discard anything else in the working tree."""
    _git(repo, "reset", "--quiet", "--keep", "HEAD~1")
