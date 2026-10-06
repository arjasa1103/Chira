"""Offline-by-default test environment.

Two hazards the suite previously inherited silently:

1. **Network.** The module docstring claimed "these are offline tests" and
   nothing enforced it. `schedule.nba_games` and `http.Client` both make live
   calls, so the first test added against either would have hit the network in
   CI with no signal.
2. **Host timezone.** `_parse_gst` on an offset-less timestamp returns a naive
   datetime whose `.timestamp()` is interpreted in the host zone. Measured: the
   same input produced epochs 7 hours apart under TZ=America/Los_Angeles vs UTC.
   That epoch is the pre-tipoff cutoff.

   **On Windows this fixture does nothing**: Python there has no
   `time.tzset`, so setting TZ does not change the process zone. That is safe
   today because no code reads host-local time (`_parse_gst` rejects naive
   timestamps outright), and it is why the one test that exercises TZ is
   skipped on Windows rather than left to pass without testing anything.
"""

from __future__ import annotations

import socket
import time

import pytest


@pytest.fixture(autouse=True)
def _fixed_tz(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    if hasattr(time, "tzset"):
        time.tzset()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, request):
    """Sockets raise unless a test is marked @pytest.mark.network."""
    if request.node.get_closest_marker("network"):
        return

    def boom(*a, **k):
        raise RuntimeError("unit tests must not open sockets; stub the client")

    monkeypatch.setattr(socket, "socket", boom)


@pytest.fixture
def sealed(monkeypatch, tmp_path):
    """Point the seal's marker at an empty directory: the holdout is CLOSED.

    This repository's own seal was opened on 2026-10-06, so a test that wants
    the closed-seal behaviour can no longer get it from the working tree.
    Both branches of `assert_scorable` are real and both are tested; without
    this the "refuses a sealed row" tests would silently start passing for
    the wrong reason, which is the failure mode they exist to catch.
    """
    import chira.holdout as H
    monkeypatch.setattr(H, "marker_path", lambda repo=".": tmp_path / H.MARKER)
    return tmp_path


@pytest.fixture
def unsealed(monkeypatch, tmp_path):
    """Point the marker at a directory that HAS one: the holdout is open."""
    import chira.holdout as H
    marker = tmp_path / H.MARKER
    marker.write_text('{"holdout_season": "2025-26"}\n', encoding="utf-8")
    monkeypatch.setattr(H, "marker_path", lambda repo=".": marker)
    return tmp_path
