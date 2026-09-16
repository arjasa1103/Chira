"""Windows portability guards that mean something on every OS.

The suite runs on Windows in CI, but the hazards below are exactly the ones a
Windows runner does NOT reliably catch, or that a macOS/Linux developer would
never see locally:

- **Text encoding.** Windows' default text encoding is cp1252, not UTF-8. Every
  file this project writes happens to be ASCII today (`json.dumps` escapes by
  default), so nothing fails yet. The first `é` in a SQL comment or a team name
  written with `ensure_ascii=False` would break only on Windows. ruff's
  PLW1514 cannot guard this: it only sees calls whose receiver it can infer is
  a `Path`, which measured at 4 of 32 real call sites. So the rule is enforced
  here, over the syntax tree.
- **Path separators and quoting.** Tested with `PureWindowsPath`, which models
  Windows paths on any OS, so a Mac run proves the Windows behaviour.
- **Time zone data.** Windows has no system tz database; `zoneinfo` needs the
  `tzdata` package, which must be declared rather than inherited by accident.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath
from zoneinfo import ZoneInfo

import pytest

from chira.snapshot import _manifest_key, _sql_path

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("src", "scripts", "tests")
TEXT_ATTRS = {"read_text", "write_text"}
NON_FILE_OPENERS = {"tarfile", "gzip", "webbrowser", "zipfile"}


def _mode(call: ast.Call, pos: int) -> str | None:
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    if len(call.args) > pos:
        arg = call.args[pos]
        return arg.value if isinstance(arg, ast.Constant) else None
    return "r"


def _text_mode_call_without_encoding(call: ast.Call) -> bool:
    if any(kw.arg == "encoding" for kw in call.keywords):
        return False
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in TEXT_ATTRS:
        return True
    if isinstance(f, ast.Name) and f.id == "open":
        mode = _mode(call, 1)
    elif isinstance(f, ast.Attribute) and f.attr == "open":
        if isinstance(f.value, ast.Name) and f.value.id in NON_FILE_OPENERS:
            return False
        mode = _mode(call, 0)
    elif isinstance(f, ast.Attribute) and f.attr == "fdopen":
        mode = _mode(call, 1)
    else:
        return False
    return isinstance(mode, str) and "b" not in mode


def test_every_text_mode_file_call_names_its_encoding():
    offenders = []
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            offenders += [f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
                          for node in ast.walk(tree)
                          if isinstance(node, ast.Call)
                          and _text_mode_call_without_encoding(node)]
    assert not offenders, (
        "text-mode file I/O without encoding= uses cp1252 on Windows; "
        f'pass encoding="utf-8": {offenders}')


class TestTheGuardItself:
    """A guard that never fires is decoration. These prove it can."""

    @pytest.mark.parametrize("src", [
        "p.read_text()",
        "p.write_text(s)",
        "open(f)",
        "open(f, 'w')",
        "p.open('a')",
        "os.fdopen(fd, 'w')",
    ])
    def test_it_flags_text_mode_calls(self, src):
        call = ast.parse(src).body[0].value
        assert _text_mode_call_without_encoding(call)

    @pytest.mark.parametrize("src", [
        "p.read_text(encoding='utf-8')",
        "open(f, 'rb')",
        "p.open('rb')",
        "tarfile.open(f)",
        "open(f, mode)",   # non-literal mode: unknowable, not flagged
    ])
    def test_it_leaves_binary_and_explicit_calls_alone(self, src):
        call = ast.parse(src).body[0].value
        assert not _text_mode_call_without_encoding(call)


class TestSnapshotPaths:
    def test_manifest_keys_are_posix_even_for_windows_paths(self):
        root = PureWindowsPath(r"C:\data\snapshots\census-x")
        f = root / "games" / "sport=nba" / "season=2024-25" / "data_0.parquet"
        assert _manifest_key(f, root) == "games/sport=nba/season=2024-25/data_0.parquet"

    def test_posix_keys_are_unchanged(self):
        """The existing Mac-cut snapshot's keys must still match after the fix."""
        root = PurePosixPath("/data/snapshots/census-x")
        assert _manifest_key(root / "runs.parquet", root) == "runs.parquet"

    def test_sql_paths_use_forward_slashes(self):
        assert _sql_path(PureWindowsPath(r"C:\data\snap\games")) == "C:/data/snap/games"

    def test_sql_paths_double_single_quotes(self):
        p = PureWindowsPath(r"C:\Users\O'Neil\snap")
        assert _sql_path(p) == "C:/Users/O''Neil/snap"


class TestTimeZoneData:
    def test_eastern_time_resolves(self):
        """On Windows this raises ZoneInfoNotFoundError unless tzdata is installed."""
        assert ZoneInfo("America/New_York").key == "America/New_York"

    def test_tzdata_is_declared_directly_for_windows(self):
        """Today pandas (via nba_api) happens to pull tzdata on Windows.

        That is an accident of someone else's dependency list. If it changed,
        every Eastern-time slug date and season gate would break on Windows
        with no change in this repository.
        """
        deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        declared = [d for d in deps["project"]["dependencies"] if d.startswith("tzdata")]
        assert declared and "win32" in declared[0]
