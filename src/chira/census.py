"""The census runner: schedule in, `priced` and `misses` out.

Every design choice here exists to protect one number. The coverage chart that
gates the project is `priced / scheduled`, and the way that number goes wrong is
never a crash -- it is a game quietly landing in neither table, or landing in
`misses` because of a slug variant nobody tried.

So:

- Enumeration is driven by the league schedule, never by paginating Gamma.
- A miss records EVERY slug attempted, so "no market exists" and "we never
  tried the right slug" stay distinguishable forever.
- Every `no_market` is re-probed once with the cache bypassed (E6) before it is
  believed, because an empty `/events` response and a transient upstream failure
  look identical.
- A game that cannot be scored (postponed, non-complementary, unresolved,
  label disagreement) goes to `misses` with its own reason rather than sitting
  in `priced` with a NULL, so the reconciliation line explains itself.
- Resume is "skip what is already settled", so a killed run costs one game.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .cache import fingerprint
from .constants import TIPOFF_ET_HOUR_BAND
from .extract import closing_price, label_agreement
from .http import Client, NetworkUnavailable
from .resolve import confirm, team_labels
from .store import Store
from .telemetry import Telemetry

ET = ZoneInfo("America/New_York")


def rematch_slugs(sport: str, games: list[dict],
                  abbr_map: dict[str, str]) -> dict[str, str]:
    """{game_id: the et_plus_1 slug that would bind the WRONG game}.

    A game whose next-day rematch has the same away/home orientation shares its
    `et_plus_1` slug with that rematch's primary slug. Measured: 19 such pairs
    across the two schedules, 10 of which share a winner, so label agreement
    cannot see the mis-binding. The fallback fires exactly in the contaminated
    Oct-Dec 2025 window where those slugs are most likely to be reached.
    """
    by_key: dict[tuple[str, str, str], set[str]] = {}
    for g in games:
        by_key.setdefault((g["away"], g["home"], g["et_date"]), set()).add(g["game_id"])
    blocked: dict[str, str] = {}
    for g in games:
        nxt = (date.fromisoformat(g["et_date"]) + timedelta(days=1)).isoformat()
        if (g["away"], g["home"], nxt) in by_key:
            a = abbr_map.get(g["away"], g["away"])
            h = abbr_map.get(g["home"], g["home"])
            blocked[g["game_id"]] = f"{sport}-{a}-{h}-{nxt}"
    return blocked


def tipoff_is_plausible(gst: str | None, et_date: str) -> tuple[bool, str]:
    """Does the market's tipoff agree with the league schedule?

    `gameStartTime` comes from the same third party being benchmarked and is the
    pre-tipoff cutoff, so a late one admits in-game and settled quotes into the
    "closing" price. Verified live: nba-dal-uta-2024-11-14 carries a 00:57 ET
    tipoff and a stored p_home_close of 0.9995 on a 115-113 game.
    """
    if not gst:
        return False, "missing"
    try:
        dt = datetime.fromisoformat(gst)
    except (TypeError, ValueError):
        return False, "unparseable"
    if dt.tzinfo is None:
        return False, "naive"
    local = dt.astimezone(ET)
    if local.date().isoformat() != et_date:
        return False, f"ET date {local.date()} != schedule {et_date}"
    lo, hi = TIPOFF_ET_HOUR_BAND
    if not lo <= local.hour <= hi:
        return False, f"ET hour {local.hour} outside {TIPOFF_ET_HOUR_BAND}"
    return True, ""


def _volume(market: dict) -> float | None:
    for key in ("volumeNum", "volume"):
        v = market.get(key)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                continue
    return None


def census_game(client: Client, sport: str, game: dict, abbr_map: dict[str, str],
                labels: dict[str, tuple[str, ...]], *, bypass_cache: bool = False,
                blocked: dict[str, str] | None = None) -> dict:
    """Resolve one game to either a priced row or a classified miss.

    Returns {'outcome': 'priced'|'miss', 'attempted': [...], plus either 'row'
    or 'reason'/'detail'}. Never raises on remote data: the caller is mid-census.
    """
    away = abbr_map.get(game["away"], game["away"])
    home = abbr_map.get(game["home"], game["home"])
    block = {blocked[game["game_id"]]} if blocked and game["game_id"] in blocked else None
    hit = confirm(client, sport, game, away, home, labels,
                  bypass_cache=bypass_cache, blocked=block)
    attempted = hit["attempted"]
    if not hit["market"]:
        # "No market exists", "a market is there under labels we did not
        # recognise", and "the teams matched but only spread / half-game markets"
        # are different facts, and only the first licenses the coverage conclusion.
        if hit.get("rejected_types"):
            return {"outcome": "miss", "reason": "no_moneyline_market",
                    "attempted": attempted,
                    "detail": f"label-matching markets were typed {hit['rejected_types']}"}
        return {"outcome": "miss",
                "reason": "label_mismatch_at_slug" if hit["saw_events"] else "no_market",
                "attempted": attempted,
                "detail": "slug returned events that matched no team labels"
                          if hit["saw_events"] else None}

    market = hit["market"]
    league_tip = game.get("start_time_utc")
    if not league_tip:
        # Fallback only. With the league's own start time the cutoff no longer
        # depends on Gamma's timestamp, and the ET-hour band both missed 4-hour
        # errors and rejected a real 09:00 ET game in Stockholm.
        ok, why = tipoff_is_plausible(market.get("gameStartTime"), game["et_date"])
        if not ok:
            return {"outcome": "miss", "reason": "implausible_game_start_time",
                    "attempted": attempted,
                    "detail": f"{hit['slug']}: gameStartTime "
                              f"{market.get('gameStartTime')!r} ({why})"}
    cp = closing_price(client, market, tip_utc=league_tip)
    if not cp.get("ok"):
        return {"outcome": "miss", "reason": cp.get("reason", "unparseable_market"),
                "attempted": attempted, "detail": hit["slug"]}

    # Complementarity. False is a hard failure; None means the away series was
    # absent so the check could not run, which is recorded, not silently passed.
    if cp.get("complement_ok") is False:
        return {"outcome": "miss", "reason": "complementarity_failed",
                "attempted": attempted,
                "detail": (f"{hit['slug']} share={cp.get('complement_share')} "
                           f"pairs={cp.get('complement_pairs')} "
                           f"last_sum={cp.get('complement_sum')}")}

    if cp.get("reason_excluded"):
        return {"outcome": "miss", "reason": cp["reason_excluded"],
                "attempted": attempted, "detail": hit["slug"]}

    agreement = label_agreement(cp.get("market_winner"), game["winner"])
    if agreement == "unresolved":
        return {"outcome": "miss", "reason": "unresolved_market",
                "attempted": attempted, "detail": hit["slug"]}
    if agreement == "disagree":
        # E1. The market and the league disagree about who won. Either the
        # orientation chain is flipped or the slug matched the wrong game, and
        # both are worse than a missing row.
        return {"outcome": "miss", "reason": "label_disagreement",
                "attempted": attempted,
                "detail": (f"{hit['slug']}: market={cp.get('market_winner')} "
                           f"league={game['winner']}")}

    row = {
        "slug": hit["slug"],
        "convention": hit["convention"],
        "away_nickname": cp.get("away_nickname"),
        "home_nickname": cp.get("home_nickname"),
        "p_home_close": cp["p_home_close"],
        "p_home_t1h": cp.get("p_home_t1h"),
        "p_home_t6h": cp.get("p_home_t6h"),
        "p_home_t24h": cp.get("p_home_t24h"),
        "n_pre_tipoff": cp["n_pre_tipoff"],
        "secs_before_tip": cp["secs_before_tip"],
        "stale_flat_run": cp.get("stale_flat_run"),
        "complement_sum": cp.get("complement_sum"),
        "complement_ok": cp.get("complement_ok"),
        "market_winner": cp.get("market_winner"),
        "label_agreement": agreement,
        "volume": _volume(market),
        "game_start_time": market.get("gameStartTime"),
        "market_type": market.get("sportsMarketType"),
        "market_question": market.get("question"),
        "cutoff_source": cp.get("cutoff_source"),
        "league_start_time": league_tip if cp.get("cutoff_source") == "league" else None,
        "gamma_delta_min": cp.get("gamma_delta_min"),
        "p_home_close_gamma": cp.get("p_home_close_gamma"),
        "complement_share": cp.get("complement_share"),
        "complement_pairs": cp.get("complement_pairs"),
    }
    return {"outcome": "priced", "row": row, "attempted": attempted,
            "series": cp.get("series")}


# How long a census waits out a local network outage before giving up. Measured
# cause on 2026-09-13: the laptop slept mid-run and DNS stopped resolving. Waiting
# is safe because census_game writes nothing until a game is fully resolved, so a
# retried game starts clean; its already-fetched payloads come back from cache.
NETWORK_PATIENCE_SECONDS = 2 * 3600
NETWORK_WAIT_START = 30.0
NETWORK_WAIT_CAP = 300.0


def _patiently(tel: Telemetry, fn):
    """Call fn, waiting out NetworkUnavailable with capped backoff; re-raise past patience."""
    waited, wait = 0.0, NETWORK_WAIT_START
    while True:
        try:
            return fn()
        except NetworkUnavailable as e:
            if waited >= NETWORK_PATIENCE_SECONDS:
                raise
            tel.event("network_wait", seconds=wait, waited=waited, error=str(e)[:200])
            time.sleep(wait)
            waited += wait
            wait = min(wait * 2, NETWORK_WAIT_CAP)


def slice_games(games: list[dict], limit: int | None, strategy: str = "stride") -> list[dict]:
    """Pick `limit` games for a partial run.

    `stride` takes every k-th game across the season. This is not a detail: the
    first NHL gate slice took the first 200 games in date order and returned
    **0 priced, 200 misses**, because Polymarket's NHL coverage does not start
    at the season opener. A gate with no priced rows cannot check label
    agreement, complementarity, or the join -- the three things it exists for.

    `head` is the full-run order (date ascending), kept for a real census where
    every game is fetched anyway and resumability wants a stable order.
    """
    if limit is None or limit >= len(games):
        return list(games)
    if strategy == "head":
        return games[:limit]
    if strategy != "stride":
        raise ValueError(f"unknown slice strategy {strategy!r}")
    step = len(games) / limit
    picked = [games[min(int(i * step), len(games) - 1)] for i in range(limit)]
    # int() rounding can repeat an index at small limits; dedupe by game_id.
    seen, out = set(), []
    for g in picked:
        if g["game_id"] not in seen:
            seen.add(g["game_id"])
            out.append(g)
    return out


def run_census(client: Client, store: Store, tel: Telemetry, sport: str, season: str,
               games: list[dict], abbr_map: dict[str, str], *,
               limit: int | None = None, resume: bool = True,
               strategy: str = "stride", verbose: bool = False) -> dict:
    """Census `games` into the store. Idempotent; safe to re-run.

    `limit` is the week-2 validation gate's handle: run a slice, check the gate,
    and only then spend 15,000 requests.
    """
    store.put_games(sport, season, games)
    labels = team_labels(games)
    settled = store.settled_game_ids(sport, season) if resume else set()
    todo = slice_games([g for g in games if g["game_id"] not in settled],
                       limit, strategy)
    tel.event("census_start", sport=sport, season=season, scheduled=len(games),
              already_settled=len(settled), todo=len(todo), strategy=strategy,
              date_span=[todo[0]["et_date"], todo[-1]["et_date"]] if todo else None)

    blocked = rematch_slugs(sport, games, abbr_map)
    tel.event("rematch_guard", sport=sport, season=season, blocked_games=len(blocked))
    counts: dict[str, int] = {"priced": 0, "miss": 0}
    for i, g in enumerate(todo, 1):
        res = _patiently(tel, lambda g=g: census_game(client, sport, g, abbr_map, labels,
                                                       blocked=blocked))
        if res["outcome"] == "priced":
            store.put_priced(sport, season, g["game_id"], res["row"],
                             points=res.get("series"))
            counts["priced"] += 1
            tel.event("game", sport=sport, season=season, game_id=g["game_id"],
                      outcome="priced", slug=res["row"]["slug"],
                      convention=res["row"]["convention"],
                      p_home_close=res["row"]["p_home_close"])
        else:
            store.put_miss(sport, season, g["game_id"], res["reason"],
                           res["attempted"], res.get("detail"))
            counts["miss"] += 1
            counts[res["reason"]] = counts.get(res["reason"], 0) + 1
            tel.event("game", sport=sport, season=season, game_id=g["game_id"],
                      outcome="miss", reason=res["reason"],
                      attempted=res["attempted"], detail=res.get("detail"))
        if verbose and i % 25 == 0:
            print(f"    {sport} {season} {i}/{len(todo)}  "
                  f"priced={counts['priced']} miss={counts['miss']}", flush=True)
    tel.event("census_end", sport=sport, season=season, **counts)
    return counts


# Every reason that can be produced by an EMPTY or MALFORMED payload gets a
# cache-bypassed second look. Re-probing only `no_market` defeated the cache's
# central rule ("an empty result is never cached") through the store instead:
# settled_game_ids treats any miss as settled, so a transient empty that landed
# as no_pre_tipoff_points or unparseable_market was frozen into the dataset on
# the first run and never looked at again.
REPROBE_REASONS = (
    "no_market",
    "label_mismatch_at_slug",
    "no_pre_tipoff_points",
    "unparseable_market",
    "unresolved_market",
    "missing_gameStartTime",
    "unparseable_gameStartTime",
)


def reprobe_misses(client: Client, store: Store, tel: Telemetry, sport: str, season: str,
                   games: list[dict], abbr_map: dict[str, str], *,
                   reasons: tuple[str, ...] = REPROBE_REASONS) -> dict:
    """E6 second pass: re-probe every `no_market` with the cache bypassed.

    An empty `/events?slug=` response is indistinguishable from a transient
    upstream failure, and the cache never stores an empty result precisely so
    this pass can be meaningful. A miss that survives a cache-bypassed re-probe
    is a real miss; one that does not was an artifact.
    """
    if not reasons:
        raise ValueError("reasons must be non-empty; an empty IN () is invalid SQL")
    labels = team_labels(games)
    blocked = rematch_slugs(sport, games, abbr_map)
    by_id = {g["game_id"]: g for g in games}
    rows = store.db.execute(
        f"SELECT game_id, reason FROM misses WHERE sport=? AND season=? "
        f"AND reason IN ({','.join('?' * len(reasons))})",
        [sport, season, *reasons]).fetchall()
    out = {"reprobed": 0, "recovered": 0, "still_missing": 0, "not_in_schedule": 0}
    for game_id, _reason in rows:
        g = by_id.get(game_id)
        if g is None:
            # A schedule that shifted between the census pass and this one leaves
            # these misses permanently un-re-probed. Counted, not swallowed: E6's
            # second pass quietly not running must not look like it ran clean.
            out["not_in_schedule"] += 1
            continue
        out["reprobed"] += 1
        res = _patiently(tel, lambda g=g: census_game(client, sport, g, abbr_map, labels,
                                                       bypass_cache=True, blocked=blocked))
        if res["outcome"] == "priced":
            store.put_priced(sport, season, game_id, res["row"],
                             points=res.get("series"))
            out["recovered"] += 1
            tel.event("reprobe_recovered", sport=sport, season=season,
                      game_id=game_id, slug=res["row"]["slug"])
        else:
            store.put_miss(sport, season, game_id, res["reason"],
                           res["attempted"], res.get("detail"))
            out["still_missing"] += 1
    tel.event("reprobe_end", sport=sport, season=season, **out)
    return out


def load_abbr_map(path: str, season: str, sport: str) -> dict[str, str]:
    """Read one sport-season map out of data/abbr_map_resolved.json.

    Raises on an unresolved team. A partially resolved map silently books every
    game of the missing team as `no_market`: Vegas alone is 164 games across the
    two seasons, which is 3% of the sample and enough to move the coverage
    chart that decides the primary sport.
    """
    doc = json.loads(Path(path).read_text())
    entry = ((doc.get("seasons") or {}).get(season) or {}).get(sport)
    if not entry:
        raise KeyError(f"no resolved abbreviation map for {sport} {season} in {path}")
    if entry.get("unresolved"):
        raise ValueError(
            f"{sport} {season} has unresolved teams {entry['unresolved']}; "
            f"re-run scripts/resolve_abbrs.py before the census")
    return dict(entry["map"])


def map_fingerprint(abbr_map: dict[str, str]) -> str:
    return fingerprint(abbr_map)


def manifest(sport: str, season: str, games: list[dict], abbr_map: dict[str, str],
             **extra: Any) -> dict:
    dates = sorted(g["et_date"] for g in games)
    return {
        "sport": sport,
        "season": season,
        "scheduled": len(games),
        "date_window": [dates[0], dates[-1]] if dates else None,
        "abbr_map_fingerprint": map_fingerprint(abbr_map),
        "abbr_map_irregulars": {k: v for k, v in abbr_map.items() if k != v},
        **extra,
    }
