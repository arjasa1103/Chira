"""Immutable Parquet snapshot of a finished census (T7, E13).

Every phase after week 3 reads the snapshot, never the live store and never the
network. That is the whole point: one unauthenticated third-party API with no
contract, over a multi-month project, is not something the analysis should be
able to reach.

What makes it trustworthy rather than just a copy:

- **Refuses an unfinished census.** Every sport-season must satisfy
  `scheduled == priced + misses` with no orphans, no double counts, and every
  priced game carrying its raw series. A snapshot of a partial pass would be a
  coverage number with a hole in its denominator.
- **Atomic.** Written into a temporary sibling directory and renamed into place,
  so a snapshot directory under its real name is always complete.
- **Content-addressed and checksummed.** The directory name carries the store
  digest; the manifest carries a SHA-256 for every file. `verify_snapshot`
  also rejects files the manifest does not list.
- **Read-only on disk.** Files 0444, directories 0555. Not security, just a
  speed bump against editing a published input by accident.
- **Timezone-proof.** `game_start_time` is written as ISO-8601 text with an
  explicit +00 offset. DuckDB renders TIMESTAMPTZ in the READER's session zone,
  so a TIMESTAMPTZ column in a released file shows different values on
  different machines.
- **Partitioned by sport and season** (E13), so a consumer reads one partition
  without scanning ~120M raw price rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
from pathlib import Path

import duckdb

from .store import SCHEMA_VERSION, Store
from .telemetry import git_hash

SNAPSHOT_FORMAT = 1

# (table, SELECT list, partitioned). ORDER BY makes files reproducible for a
# given store state; game_start_time is cast to text for the timezone reason
# in the module docstring.
_TABLES: tuple[tuple[str, str, bool], ...] = (
    ("games", "* REPLACE (strftime(start_time_utc AT TIME ZONE 'UTC', "
              "'%Y-%m-%dT%H:%M:%S+00:00') AS start_time_utc)", True),
    ("priced", "* REPLACE (strftime(game_start_time AT TIME ZONE 'UTC', "
               "'%Y-%m-%dT%H:%M:%S+00:00') AS game_start_time, "
               "strftime(league_start_time AT TIME ZONE 'UTC', "
               "'%Y-%m-%dT%H:%M:%S+00:00') AS league_start_time)", True),
    ("misses", "*", True),
    ("price_points", "*", True),
    ("runs", "run_id, CAST(started_at AS VARCHAR) AS started_at, "
             "CAST(finished_at AS VARCHAR) AS finished_at, manifest", False),
)
_ORDER = {
    "games": "sport, season, game_id",
    "priced": "sport, season, game_id",
    "misses": "sport, season, game_id",
    "price_points": "sport, season, game_id, side, t",
    "runs": "started_at, run_id",
}

VOLUME_DEFINITION = (
    "priced.volume is the market's TERMINAL cumulative volume as reported by "
    "Gamma at census time (volumeNum, else volume). It is outcome-correlated "
    "(close games attract volume) and mutable upstream; PREREGISTRATION.md "
    "requires it frozen here and reported with that caveat."
)
TIMESTAMP_CONVENTION = (
    "priced.game_start_time (Gamma's), priced.league_start_time and "
    "games.start_time_utc are ISO-8601 text with an explicit +00:00 offset (UTC). "
    "priced.cutoff_source says which one the closing price was cut at. "
    "price_points.t is unix seconds. games.et_date is the US-Eastern calendar date."
)


class SnapshotError(RuntimeError):
    """The snapshot is incomplete, tampered with, or would overwrite another."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sport_seasons(store: Store) -> list[tuple[str, str]]:
    return [tuple(r) for r in store.db.execute(
        "SELECT DISTINCT sport, season FROM games ORDER BY sport, season").fetchall()]


def preflight(store: Store) -> dict:
    """Everything that must hold before a snapshot may be cut. Raises SnapshotError."""
    pairs = _sport_seasons(store)
    if not pairs:
        raise SnapshotError("the store has no scheduled games")
    report = {}
    for sport, season in pairs:
        try:
            rec = store.assert_reconciled(sport, season, require_complete=True)
        except AssertionError as e:
            raise SnapshotError(f"refusing to snapshot an unfinished census: {e}") from e
        pts = store.points_summary(sport, season)
        if pts["priced_missing_series"] or pts["orphan_series"]:
            raise SnapshotError(
                f"{sport}/{season}: {pts['priced_missing_series']} priced games have "
                f"no raw series and {pts['orphan_series']} series have no priced game")
        report[f"{sport}/{season}"] = {**rec, "price_points": pts}
    return report


def create_snapshot(store: Store, root: str | Path, *, immutable: bool = True) -> Path:
    """Cut a snapshot under `root`. Returns its directory. Never overwrites."""
    reconciliation = preflight(store)
    digest = store.digest()
    snap_id = f"census-{time.strftime('%Y%m%d', time.gmtime())}-{digest[:12]}"
    root = Path(root)
    dest = root / snap_id
    if dest.exists():
        raise SnapshotError(f"{dest} already exists; snapshots are immutable")
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".tmp-{snap_id}-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()

    try:
        tables = {}
        for name, select, partitioned in _TABLES:
            query = f"SELECT {select} FROM {name} ORDER BY {_ORDER[name]}"
            if partitioned:
                target = tmp / name
                store.db.execute(
                    f"COPY ({query}) TO '{target}' (FORMAT parquet, COMPRESSION zstd, "
                    f"PARTITION_BY (sport, season))")
                parts = dict(store.db.execute(
                    f"SELECT sport || '/' || season, count(*) FROM {name} "
                    f"GROUP BY ALL ORDER BY ALL").fetchall())
            else:
                target = tmp / f"{name}.parquet"
                store.db.execute(
                    f"COPY ({query}) TO '{target}' (FORMAT parquet, COMPRESSION zstd)")
                parts = {}
            rows = store.db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            tables[name] = {"rows": rows, "partitions": parts}

        files = {str(p.relative_to(tmp)): _sha256(p)
                 for p in sorted(tmp.rglob("*")) if p.is_file()}
        manifest = {
            "snapshot_format": SNAPSHOT_FORMAT,
            "snapshot_id": snap_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "git_hash": git_hash(),
            "schema_version": SCHEMA_VERSION,
            "store_digest": digest,
            "tables": tables,
            "reconciliation": reconciliation,
            "miss_reasons": store.miss_reasons(),
            "runs": [r[0] for r in store.db.execute(
                "SELECT run_id FROM runs ORDER BY started_at").fetchall()],
            "volume_definition": VOLUME_DEFINITION,
            "timestamp_convention": TIMESTAMP_CONVENTION,
            "files": files,
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
        os.rename(tmp, dest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    if immutable:
        make_read_only(dest)
    return dest


def make_read_only(path: Path) -> None:
    for p in sorted(path.rglob("*"), reverse=True):
        p.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
                | ((stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) if p.is_dir() else 0))
    path.chmod(0o555)


def make_writable(path: Path) -> None:
    """For deliberately deleting a snapshot (and for tests). Never called by the pipeline."""
    path.chmod(0o755)
    for p in path.rglob("*"):
        p.chmod(0o755 if p.is_dir() else 0o644)


def verify_snapshot(path: str | Path) -> dict:
    """Recompute every checksum and reject unlisted files. Returns the manifest."""
    path = Path(path)
    mpath = path / "manifest.json"
    if not mpath.is_file():
        raise SnapshotError(f"{path} has no manifest.json")
    manifest = json.loads(mpath.read_text())
    listed = manifest.get("files") or {}
    on_disk = {str(p.relative_to(path)) for p in path.rglob("*")
               if p.is_file() and p.name != "manifest.json"}
    extra = sorted(on_disk - set(listed))
    missing = sorted(set(listed) - on_disk)
    if extra or missing:
        raise SnapshotError(f"file set does not match manifest: extra={extra[:5]} "
                            f"missing={missing[:5]}")
    bad = [rel for rel, want in listed.items() if _sha256(path / rel) != want]
    if bad:
        raise SnapshotError(f"{len(bad)} files fail their checksum: {bad[:5]}")
    return manifest


def open_snapshot(path: str | Path, *, verify: bool = True) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB with one view per snapshot table. No network, no store."""
    path = Path(path)
    manifest = verify_snapshot(path) if verify else json.loads(
        (path / "manifest.json").read_text())
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='UTC'")
    for name, _select, partitioned in _TABLES:
        if manifest["tables"].get(name, {}).get("rows", 0) == 0:
            continue
        src = (f"read_parquet('{path / name}/**/*.parquet', hive_partitioning=true, "
               f"hive_types={{'sport': 'VARCHAR', 'season': 'VARCHAR'}})"
               if partitioned else f"read_parquet('{path / name}.parquet')")
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM {src}")
    return con
