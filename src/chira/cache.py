"""On-disk response cache (E6).

The census is ~15,300 requests over days, so a cache is not an optimization,
it is what makes a re-run cheap enough to be honest. But a naive cache is
actively dangerous here, in three specific ways this module is built around:

1. **A WAF challenge page is an HTTP 200 with HTML.** Caching it turns one
   transient block into a permanent fabricated answer. Only payloads that pass
   an endpoint's schema validator are ever written (see `http.Client.get_json`,
   which refuses non-JSON 200s before this module sees them).

2. **An empty result is ambiguous, so it is NEVER cached.** `/events?slug=` on
   a slug that has no market returns `[]`, and so does the same call while the
   upstream is half-broken. Caching `[]` freezes "no market exists" into the
   dataset, where it is indistinguishable from a real miss and keeps the
   reconciliation assert perfectly balanced. Every miss stays re-probeable,
   which is what E6's second-pass re-probe requires.

3. **The abbreviation map is an input to every slug.** If the map changes, every
   cached slug lookup computed under the old map is stale, so those keys include
   a map fingerprint and a corrected abbreviation invalidates them automatically.

   That fingerprint is scoped to SLUG-DERIVED urls only. It used to be mixed into
   every key, including prices-history, which is addressed by CLOB token id and
   has no dependency on the abbreviation map at all. Measured cost of that
   mistake: 0.84 MB of cache per priced game, so correcting one team's
   abbreviation would have thrown away ~3.4 GB of price history and ~2 hours of
   re-fetching to fix something that can only affect `/events?slug=`.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def fingerprint(obj: Any) -> str:
    """Stable short hash of any JSON-serializable object."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


class Cache:
    """Content-addressed JSON cache under `root`, sharded two hex characters deep."""

    def __init__(self, root: str | Path, *, abbr_version: str,
                 schema_version: int = SCHEMA_VERSION) -> None:
        self.root = Path(root)
        self.abbr_version = abbr_version
        self.schema_version = schema_version
        self.stats: Counter[str] = Counter()
        self.last_error: str | None = None

    def abbr_sensitive(self, url: str) -> bool:
        """True for slug lookups, whose RESULT depends on the abbreviation map.

        Everything else (prices-history by token id, club-schedule by team) is
        addressed by an identifier the map cannot change.
        """
        return "slug=" in url

    def key(self, url: str) -> str:
        version = self.abbr_version if self.abbr_sensitive(url) else "-"
        return hashlib.sha256(
            f"{self.schema_version}|{version}|{url}".encode()
        ).hexdigest()

    def path(self, url: str) -> Path:
        k = self.key(url)
        return self.root / k[:2] / f"{k}.json"

    def get(self, url: str) -> Any | None:
        p = self.path(url)
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.stats["miss"] += 1
            return None
        except (OSError, json.JSONDecodeError):
            # A truncated entry (killed mid-write on an older run, or a full
            # disk) must behave as a miss, not as an exception that aborts a
            # census 9,000 requests in.
            self.stats["corrupt"] += 1
            return None
        if entry.get("url") != url:
            self.stats["collision"] += 1  # cannot happen with sha256; counted anyway
            return None
        self.stats["hit"] += 1
        return entry.get("payload")

    def put(self, url: str, payload: Any) -> None:
        """Write atomically, and never let a cache failure end a census.

        A cache write is an optimization. The census projects to ~3.4 GB of cached
        responses, so ENOSPC at request 12,000 is a realistic way to end a
        multi-day run -- and ending it is the one thing the whole resumable design
        exists to prevent. Serialization bugs still raise, because those are ours.
        """
        p = self.path(url)
        p.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "url": url,
            "schema_version": self.schema_version,
            "abbr_version": self.abbr_version,
            "payload": payload,
        }
        try:
            fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        except OSError as e:
            self.stats["put_failed"] += 1
            self.last_error = str(e)
            return
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entry, fh)
            os.replace(tmp, p)
        except OSError as e:
            Path(tmp).unlink(missing_ok=True)
            self.stats["put_failed"] += 1
            self.last_error = str(e)
            return
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self.stats["put"] += 1
