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

from .constants import COMPLEMENTARITY_TOL, STALE_FLAT_RUN
from .http import Client


def _parse_gst(gst: str) -> datetime:
    return datetime.fromisoformat(gst.replace(" ", "T").replace("+00", "+00:00"))


def closing_price(client: Client, market: dict, *, want_complement_check: bool = True) -> dict:
    """Extract the home-side closing price plus provenance and quality flags."""
    toks = json.loads(market["clobTokenIds"])
    outs = json.loads(market["outcomes"])
    gst = market.get("gameStartTime")
    if not gst or len(toks) != 2:
        return {"ok": False, "reason": "missing_gameStartTime_or_tokens"}
    tip = _parse_gst(gst).timestamp()
    start = _parse_gst(market["startDate"].replace("Z", "+00:00")).timestamp() \
        if market.get("startDate") else tip - 7 * 86400

    def series(token: str) -> list[dict]:
        h = client.prices_history(token, int(start) - 3600, fidelity=1)
        return [pt for pt in h if pt["t"] <= tip]

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

    if want_complement_check:
        away_pre = series(toks[0])
        if away_pre:
            s = away_pre[-1]["p"] + home_pre[-1]["p"]
            out["complement_sum"] = round(s, 6)
            out["complement_ok"] = abs(s - 1.0) < COMPLEMENTARITY_TOL

    # resolved label, from the same third party being benchmarked
    op = market.get("outcomePrices")
    if op:
        try:
            vals = [float(x) for x in json.loads(op)]
            if len(vals) == 2 and abs(vals[0] + vals[1] - 1.0) < 1e-6:
                out["market_winner"] = "home" if vals[1] > vals[0] else "away"
            elif len(vals) == 2 and abs(vals[0] - 0.5) < 1e-9:
                out["market_winner"] = None
                out["reason_excluded"] = "postponed_or_split_resolution"
        except (json.JSONDecodeError, ValueError):
            pass
    return out


def label_agreement(market_winner: str | None, schedule_winner: str) -> str:
    """E1: the strongest self-test available. Returns 'agree'|'disagree'|'unresolved'."""
    if market_winner is None:
        return "unresolved"
    return "agree" if market_winner == schedule_winner else "disagree"
