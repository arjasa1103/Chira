"""Structured run log and run manifest (T13).

A 15,300-request census that prints nothing is a census you cannot debug after
the fact. The failure this prevents is specific: the run finishes, the coverage
number looks slightly off, and there is no record of WHICH games were slow,
retried, cached, or re-probed, so the only way to investigate is to run it again
and hope the anomaly repeats.

One JSONL line per event, flushed immediately, because the interesting lines are
the ones written just before a crash.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .cache import SCHEMA_VERSION


def git_hash() -> str:
    """Short HEAD hash, or 'unknown'. The manifest ties data to the code that made it."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5, check=False)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run_id(prefix: str = "census") -> str:
    return f"{prefix}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}"


class Telemetry:
    """JSONL writer plus the manifest that describes the run."""

    def __init__(self, path: str | Path | None, rid: str, manifest: dict) -> None:
        self.rid = rid
        self.counts: dict[str, int] = {}
        self.manifest = {
            "run_id": rid,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "git_hash": git_hash(),
            "cache_schema_version": SCHEMA_VERSION,
            **manifest,
        }
        self._fh = None
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._fh = p.open("a", encoding="utf-8")
            self.event("run_start", **self.manifest)

    def event(self, kind: str, **fields: Any) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if self._fh is None:
            return
        line = {"ts": time.time(), "run_id": self.rid, "kind": kind, **fields}
        self._fh.write(json.dumps(line, default=str) + "\n")
        self._fh.flush()  # the line before the crash is the one that matters

    def close(self, **summary: Any) -> dict:
        self.event("run_end", counts=dict(self.counts), **summary)
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        return dict(self.counts)
