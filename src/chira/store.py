"""DuckDB census store: idempotent writes and the reconciliation identity (T2, T6).

Two invariants, both enforced here rather than documented and hoped for:

1. **Every scheduled game is in exactly one of `priced` or `misses`.** Writing
   one side deletes the other side's row for that game, so a game that gets a
   price on a re-run stops being a miss in the same transaction.

2. **`scheduled == priced + misses` at the end of a pass.** Checked by
   `reconcile()`, which also reports `pending` so a mid-run check cannot be
   mistaken for a passing final one.

Idempotency (T6) is primary keys plus `INSERT OR REPLACE`: a run killed at
request 9,000 and resumed writes the same rows again instead of appending a
second copy. Resume equality (E20) is `digest()`, which canonically sorts, drops
run metadata, and rounds floats -- never byte comparison, because DuckDB's
parallel aggregation does not fix float summation order and the telemetry makes
two runs differ by design.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb

from .constants import MISS_REASONS

SCHEMA = Path(__file__).with_name("schema.sql")

# Bump when schema.sql changes, and add the forward-only statements below.
#
# Without this, `CREATE TABLE IF NOT EXISTS` made the store immutable the moment
# it existed: every later edit to schema.sql was silently ignored and the next
# write died with a Binder Error. Mid-census the only remedies were deleting an
# in-progress store (~15,000 paid requests) or hand-patching the file. Verified
# on duckdb 1.5.5.
#
#   1: the original week-2 schema
#   2: run_id on games/priced/misses, so a resumed census across a code change
#      is not an unlabelled mixture
SCHEMA_VERSION = 2

_MIGRATIONS: dict[int, tuple[str, ...]] = {
    2: (
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS run_id TEXT",
        "ALTER TABLE priced ADD COLUMN IF NOT EXISTS run_id TEXT",
        "ALTER TABLE misses ADD COLUMN IF NOT EXISTS run_id TEXT",
    ),
}

_PRICED_COLS = (
    "sport", "season", "game_id", "slug", "convention", "away_nickname",
    "home_nickname", "p_home_close", "p_home_t1h", "n_pre_tipoff",
    "secs_before_tip", "stale_flat_run", "complement_sum", "complement_ok",
    "market_winner", "label_agreement", "volume", "game_start_time", "run_id",
)
_GAME_COLS = (
    "sport", "season", "game_id", "et_date", "away", "home", "away_pts",
    "home_pts", "winner", "neutral_site", "run_id",
)
_MISS_COLS = ("sport", "season", "game_id", "reason", "attempted", "detail",
              "run_id")

# DuckDB converts TIMESTAMPTZ to a Python object via pytz, which is not a
# dependency and should not become one. Reading these columns as text keeps the
# store dependency-free and gives the digest a canonical form for free.
_TZ_COLS = frozenset({"game_start_time"})


def _scope(sport: str | None, season: str | None,
           prefix: str = "") -> tuple[str, list]:
    """One filter builder for every read method.

    Four sibling readers used to filter four different ways: `reconcile` handled
    season-only, `miss_reasons` and `priced_rows` SILENTLY IGNORED it and
    returned every season, and `label_agreement` took no season argument at all.
    `priced_rows(season="2024-25")` quietly returned 2025-26 rows too.
    """
    clauses, args = [], []
    if sport:
        clauses.append(f"{prefix}sport=?")
        args.append(sport)
    if season:
        clauses.append(f"{prefix}season=?")
        args.append(season)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


def _select(cols: tuple[str, ...]) -> str:
    return ",".join(f"CAST({c} AS VARCHAR) AS {c}" if c in _TZ_COLS else c for c in cols)


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = duckdb.connect(self.path)
        # Pin the session timezone. DuckDB renders TIMESTAMPTZ in the session
        # zone, which it reads from the OS and NOT from the TZ environment
        # variable: a game stored as "2025-01-16 00:30:00+00" read back as
        # "2025-01-15 20:30:00-04" on this machine. That makes `digest()`
        # host-dependent, which would break resume equality (E20) across
        # machines, and it is the same class of bug as the naive-datetime drift
        # fixed in extract._parse_gst.
        self.db.execute("SET TimeZone='UTC'")
        self.run_id: str | None = None
        self._migrate()

    def _migrate(self) -> None:
        """Create or upgrade the schema. Forward-only, one transaction per step."""
        existed = self.db.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'games'"
        ).fetchone()[0] > 0
        self.db.execute(SCHEMA.read_text())
        current = self.db.execute(
            "SELECT v FROM meta WHERE k = 'schema_version'").fetchone()
        if current is not None:
            version = int(current[0])
        elif existed:
            version = 1  # pre-dates the meta table
        else:
            version = SCHEMA_VERSION  # fresh store, schema.sql is already current
        for step in range(version + 1, SCHEMA_VERSION + 1):
            self.db.execute("BEGIN")
            try:
                for stmt in _MIGRATIONS.get(step, ()):
                    self.db.execute(stmt)
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        self.db.execute(
            "INSERT OR REPLACE INTO meta (k, v) VALUES ('schema_version', ?)",
            [str(SCHEMA_VERSION)])

    @property
    def schema_version(self) -> int:
        return int(self.db.execute(
            "SELECT v FROM meta WHERE k = 'schema_version'").fetchone()[0])

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- writes -----------------------------------------------------------

    def put_games(self, sport: str, season: str, games: list[dict]) -> int:
        rows = [
            (sport, season, g["game_id"], g["et_date"], g["away"], g["home"],
             g.get("away_pts"), g.get("home_pts"), g["winner"],
             bool(g.get("neutral_site", False)), self.run_id)
            for g in games
        ]
        if rows:
            self.db.executemany(
                f"INSERT OR REPLACE INTO games ({','.join(_GAME_COLS)}) "
                f"VALUES ({','.join('?' * len(_GAME_COLS))})", rows)
        return len(rows)

    def put_priced(self, sport: str, season: str, game_id: str, row: dict) -> None:
        vals = ([sport, season, game_id]
                + [row.get(c) for c in _PRICED_COLS[3:-1]] + [self.run_id])
        for required in ("slug", "convention", "p_home_close", "label_agreement"):
            if row.get(required) is None:
                raise ValueError(f"priced row for {game_id} missing {required!r}")
        self.db.execute("BEGIN")
        try:
            self.db.execute(
                f"INSERT OR REPLACE INTO priced ({','.join(_PRICED_COLS)}) "
                f"VALUES ({','.join('?' * len(_PRICED_COLS))})", vals)
            # A game cannot be both priced and missed. Deleting here, inside the
            # same transaction, is what keeps the reconciliation identity true
            # across a re-run that upgrades a miss into a price.
            self.db.execute(
                "DELETE FROM misses WHERE sport=? AND season=? AND game_id=?",
                [sport, season, game_id])
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def put_miss(self, sport: str, season: str, game_id: str, reason: str,
                 attempted: list[str], detail: str | None = None) -> None:
        if reason not in MISS_REASONS:
            raise ValueError(f"unknown miss reason {reason!r}; allowed: {MISS_REASONS}")
        self.db.execute("BEGIN")
        try:
            self.db.execute(
                f"INSERT OR REPLACE INTO misses ({','.join(_MISS_COLS)}) "
                f"VALUES (?,?,?,?,?,?,?)",
                [sport, season, game_id, reason, json.dumps(sorted(attempted)),
                 detail, self.run_id])
            self.db.execute(
                "DELETE FROM priced WHERE sport=? AND season=? AND game_id=?",
                [sport, season, game_id])
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def start_run(self, run_id: str, manifest: dict) -> None:
        """Record the run AND stamp it onto every row this run writes."""
        self.run_id = run_id
        self.db.execute(
            "INSERT OR REPLACE INTO runs (run_id, started_at, manifest) "
            "VALUES (?, now(), ?)", [run_id, json.dumps(manifest, sort_keys=True)])

    def finish_run(self, run_id: str) -> None:
        self.db.execute("UPDATE runs SET finished_at = now() WHERE run_id = ?", [run_id])

    # ---- reads ------------------------------------------------------------

    def settled_game_ids(self, sport: str, season: str) -> set[str]:
        """Games already resolved either way. The resume set."""
        rows = self.db.execute(
            "SELECT game_id FROM priced WHERE sport=? AND season=? "
            "UNION SELECT game_id FROM misses WHERE sport=? AND season=?",
            [sport, season, sport, season]).fetchall()
        return {r[0] for r in rows}

    def attempted_game_ids(self, sport: str, season: str) -> set[str]:
        """Alias of settled_game_ids, named for the gate's use of it.

        The gate snapshots this BEFORE injecting a fault so it can assert that
        every game the run touched is still settled. `settled` describes the
        store's state; `attempted` describes the run's intent, and the fault
        injection is about the second.
        """
        return self.settled_game_ids(sport, season)

    def assert_attempted_settled(self, sport: str, season: str,
                                 attempted: set[str]) -> int:
        """Every game in `attempted` must still be in exactly one table.

        This is the identity that holds instant by instant on a SLICE. The
        full-pass identity (`scheduled == priced + misses`) cannot see a lost
        game mid-run, because `pending > 0` is expected and a lost game just
        makes it one larger -- so a deleted priced row passed every gate.
        """
        settled = self.settled_game_ids(sport, season)
        lost = attempted - settled
        if lost:
            raise AssertionError(
                f"{len(lost)} attempted games are settled in NEITHER table for "
                f"{sport}/{season}: {sorted(lost)[:5]}")
        return len(attempted)

    def reconcile(self, sport: str | None = None, season: str | None = None) -> dict:
        """Counts plus `balanced` and `pending`.

        `pending` exists so a mid-run call cannot be read as a passing final
        check: `balanced` is only meaningful once `pending` is zero.
        """
        where, args = _scope(sport, season)
        n = {}
        for table in ("games", "priced", "misses"):
            n[table] = self.db.execute(
                f"SELECT count(*) FROM {table}{where}", args).fetchone()[0]
        pending = n["games"] - n["priced"] - n["misses"]
        return {
            "scheduled": n["games"],
            "priced": n["priced"],
            "misses": n["misses"],
            "pending": pending,
            "balanced": pending == 0,
        }

    def double_counted(self) -> int:
        """Games present in BOTH priced and misses. Must always be zero.

        The mutual delete in put_priced/put_miss is supposed to make this
        impossible, which is exactly why it gets checked: an invariant enforced
        in two places and verified in none is an invariant on trust.
        """
        return self.db.execute(
            "SELECT count(*) FROM priced p JOIN misses m USING (sport, season, game_id)"
        ).fetchone()[0]

    def orphans(self) -> int:
        """priced/miss rows with no scheduled game.

        Balance alone does not catch this: N missing denominator rows and N
        orphan numerator rows cancel out perfectly.
        """
        n = self.db.execute(
            "SELECT count(*) FROM priced p LEFT JOIN games g USING (sport, season, game_id) "
            "WHERE g.game_id IS NULL").fetchone()[0]
        return n + self.db.execute(
            "SELECT count(*) FROM misses m LEFT JOIN games g USING (sport, season, game_id) "
            "WHERE g.game_id IS NULL").fetchone()[0]

    def assert_reconciled(self, sport: str | None = None, season: str | None = None,
                          *, require_complete: bool = True) -> dict:
        """Check the reconciliation identity.

        `require_complete=False` is for a PARTIAL pass (the week-2 gate runs on
        the first 200 games of 1,230). The identity `scheduled == priced +
        misses` is a full-pass invariant, but "no game in both tables", "no
        orphan rows", and "pending never negative" hold at every instant, and
        those are the ones that catch a lost or double-counted game.
        """
        r = self.reconcile(sport, season)
        if require_complete and not r["balanced"]:
            raise AssertionError(
                f"reconciliation failed for {sport or 'all'}/{season or 'all'}: "
                f"scheduled={r['scheduled']} != priced={r['priced']} + "
                f"misses={r['misses']} (pending={r['pending']})")
        if r["pending"] < 0:
            raise AssertionError(
                f"more settled rows than scheduled games for "
                f"{sport or 'all'}/{season or 'all'}: pending={r['pending']}")
        both = self.double_counted()
        if both:
            raise AssertionError(f"{both} games are in BOTH priced and misses")
        n_orphans = self.orphans()
        if n_orphans:
            raise AssertionError(f"{n_orphans} priced/miss rows have no scheduled game")
        return r

    def miss_reasons(self, sport: str | None = None, season: str | None = None) -> dict:
        where, args = _scope(sport, season)
        rows = self.db.execute(
            f"SELECT reason, count(*) FROM misses{where} GROUP BY reason ORDER BY reason",
            args).fetchall()
        return dict(rows)

    def label_agreement(self, sport: str | None = None,
                        season: str | None = None) -> dict:
        where, args = _scope(sport, season)
        rows = self.db.execute(
            f"SELECT label_agreement, count(*) FROM priced{where} "
            f"GROUP BY label_agreement ORDER BY label_agreement", args).fetchall()
        return dict(rows)

    def priced_rows(self, sport: str | None = None, season: str | None = None) -> list[dict]:
        where, args = _scope(sport, season)
        cur = self.db.execute(
            f"SELECT {_select(_PRICED_COLS)} FROM priced{where} "
            f"ORDER BY sport, season, game_id", args)
        return [dict(zip(_PRICED_COLS, r, strict=True)) for r in cur.fetchall()]

    # ---- resume equality (E20) -------------------------------------------

    def digest(self, *, places: int = 9) -> str:
        """Content hash over the data tables only, canonically ordered.

        Deliberately NOT byte equality of the database file, and deliberately
        excludes `runs`: two runs of the same census differ in run id and
        timestamps BY DESIGN, and float summation order is not reproducible
        under parallel aggregation. Rounding to `places` is the tolerance.
        """
        h = hashlib.sha256()
        for table, cols in (("games", _GAME_COLS), ("priced", _PRICED_COLS),
                            ("misses", _MISS_COLS)):
            h.update(f"--{table}--".encode())
            rows = self.db.execute(
                f"SELECT {_select(cols)} FROM {table} ORDER BY sport, season, game_id"
            ).fetchall()
            for row in rows:
                h.update(json.dumps([_canon(v, places) for v in row],
                                    default=str).encode())
        return h.hexdigest()


def _canon(value: Any, places: int) -> Any:
    return round(value, places) if isinstance(value, float) else value
