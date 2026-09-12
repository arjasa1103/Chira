"""Closing-price extraction and the E1 label-agreement check.

Orientation chain, which is the thing most likely to be silently wrong:

    slug `<sport>-<away>-<home>-<date>`
      -> market.outcomes      = [away_nickname, home_nickname]
      -> market.clobTokenIds  = [away_token, home_token]   (index-aligned)
      -> market.outcomePrices = ["1","0"] or ["0","1"]      (index-aligned)

An orientation flip does not crash. Under a home-side-only calibration convention
it MIRRORS the calibration curve about 0.5, which looks like a finding. The only
defence is an independent label: nba_api's WL. That is the E1 assert.
"""

from __future__ import annotations

import json
from datetime import datetime

from .constants import (
    COMPLEMENTARITY_TOL,
    DEFAULT_LOOKBACK_DAYS,
    FIDELITY_MINUTES,
    HISTORY_PAD_SECONDS,
    STALE_FLAT_RUN,
    TIE_TOL,
)
from .http import Client


def _parse_gst(gst: str) -> datetime | None:
    """Parse a remote timestamp, or None if it is not ISO-shaped.

    Python 3.12's fromisoformat already accepts both shapes this project sees
    ("2025-12-01 02:00:00+00" and "...T...Z"), so no pre-normalization is needed.
    Returning None rather than raising keeps one bad row from killing a census.
    """
    try:
        dt = datetime.fromisoformat(gst)
    except (TypeError, ValueError):
        return None
    # A naive datetime's .timestamp() is interpreted in the HOST timezone.
    # Measured: the same offset-less string produced epochs 7 hours apart under
    # TZ=America/Los_Angeles vs TZ=UTC. That epoch is the pre-tipoff cutoff, so
    # on a non-UTC machine the "closing" price could be taken after tipoff.
    return dt if dt.tzinfo is not None else None


def _load_pair(market: dict, field: str) -> list | None:
    """Parse a JSON-encoded 2-element array from an untrusted market document.

    Gamma sends these as JSON *strings*, not real arrays. Every failure shape
    below was confirmed by execution: a missing key raises KeyError, a real list
    raises TypeError, a truncated value raises JSONDecodeError, and a
    wrong-length array later raises IndexError at the use site. One malformed
    market previously aborted a whole census run.
    """
    raw = market.get(field)
    if raw is None:
        return None
    try:
        val = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return None
    return val if isinstance(val, list) and len(val) == 2 else None


def closing_price(client: Client, market: dict) -> dict:
    """Extract the home-side closing price plus provenance and quality flags.

    Returns a sentinel dict on every malformed-input path. It never raises on
    bad remote data: a census of ~15,300 requests must not die on one bad row.
    """
    toks = _load_pair(market, "clobTokenIds")
    outs = _load_pair(market, "outcomes")
    gst = market.get("gameStartTime")
    if toks is None or outs is None:
        return {"ok": False, "reason": "unparseable_market"}
    if not gst:
        return {"ok": False, "reason": "missing_gameStartTime"}
    tip_dt = _parse_gst(gst)
    if tip_dt is None:
        return {"ok": False, "reason": "unparseable_gameStartTime"}
    tip = tip_dt.timestamp()
    start_dt = _parse_gst(market["startDate"]) if market.get("startDate") else None
    start = start_dt.timestamp() if start_dt else tip - DEFAULT_LOOKBACK_DAYS * 86400

    def series(token: str) -> list[dict]:
        h = client.prices_history(token, int(start) - HISTORY_PAD_SECONDS,
                                  fidelity=FIDELITY_MINUTES)
        # Validate shape before indexing: a point missing "t", or carrying "t"
        # as a string, raised KeyError/TypeError here (both confirmed).
        return [
            pt for pt in h
            if isinstance(pt, dict)
            and isinstance(pt.get("t"), (int, float))
            and isinstance(pt.get("p"), (int, float))
            and pt["t"] <= tip
        ]

    home_pre = series(toks[1])
    if not home_pre:
        return {"ok": False, "reason": "no_pre_tipoff_points"}

    out = {
        "ok": True,
        "home_nickname": outs[1],
        "away_nickname": outs[0],
        "p_home_close": home_pre[-1]["p"],
        "n_pre_tipoff": len(home_pre),
        "secs_before_tip": int(tip - home_pre[-1]["t"]),
        "p_home_t1h": next((pt["p"] for pt in reversed(home_pre)
                            if pt["t"] <= tip - 3600), None),
    }
    # staleness: a long flat run immediately pre-tipoff is carry-forward, not quoting
    tail = [pt["p"] for pt in home_pre[-STALE_FLAT_RUN:]]
    out["stale_flat_run"] = len(tail) == STALE_FLAT_RUN and len(set(tail)) == 1

    # Always set complement_ok so an absent away series is countable rather than
    # indistinguishable from a passing check.
    away_pre = series(toks[0])
    if away_pre:
        total = away_pre[-1]["p"] + home_pre[-1]["p"]
        out["complement_sum"] = round(total, 6)
        out["complement_ok"] = abs(total - 1.0) < COMPLEMENTARITY_TOL
    else:
        out["complement_sum"] = None
        out["complement_ok"] = None
        out["complement_reason"] = "no_away_series"

    # resolved label, from the same third party being benchmarked
    op = market.get("outcomePrices")
    if op:
        try:
            vals = [float(x) for x in json.loads(op)]
            if len(vals) != 2:
                out["market_winner"] = None
                out["reason_excluded"] = "malformed_outcome_prices"
            # The tie MUST be tested before the complementarity branch:
            # ["0.5","0.5"] sums to exactly 1.0, so a complementarity-first
            # ordering made this unreachable and silently labelled every
            # postponed game an away win. The sum check is kept HERE too, so a
            # non-complementary equal pair (e.g. ["0.3","0.3"]) falls through to
            # outcome_prices_not_complementary rather than being mislabelled
            # "postponed" on the census reconciliation line.
            elif (abs(vals[0] - vals[1]) < TIE_TOL
                  and abs(vals[0] + vals[1] - 1.0) < COMPLEMENTARITY_TOL):
                out["market_winner"] = None
                out["reason_excluded"] = "postponed_or_split_resolution"
            elif abs(vals[0] + vals[1] - 1.0) < COMPLEMENTARITY_TOL:
                out["market_winner"] = "home" if vals[1] > vals[0] else "away"
            else:
                out["market_winner"] = None
                out["reason_excluded"] = "outcome_prices_not_complementary"
        except (json.JSONDecodeError, ValueError):
            pass
    return out


def label_agreement(market_winner: str | None, schedule_winner: str) -> str:
    """E1: the strongest self-test available. Returns 'agree'|'disagree'|'unresolved'."""
    if market_winner is None:
        return "unresolved"
    return "agree" if market_winner == schedule_winner else "disagree"
