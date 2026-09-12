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
from pathlib import Path
from typing import Any

from .cache import fingerprint
from .extract import closing_price, label_agreement
from .http import Client
from .resolve import confirm, team_labels
from .store import Store
from .telemetry import Telemetry


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
                labels: dict[str, tuple[str, ...]], *,
                bypass_cache: bool = False) -> dict:
    """Resolve one game to either a priced row or a classified miss.

    Returns {'outcome': 'priced'|'miss', 'attempted': [...], plus either 'row'
    or 'reason'/'detail'}. Never raises on remote data: the caller is mid-census.
    """
    away = abbr_map.get(game["away"], game["away"])
    home = abbr_map.get(game["home"], game["home"])
    hit = confirm(client, sport, game, away, home, labels, bypass_cache=bypass_cache)
    attempted = hit["attempted"]
    if not hit["market"]:
        return {"outcome": "miss", "reason": "no_market", "attempted": attempted,
                "detail": None}

    market = hit["market"]
    cp = closing_price(client, market)
    if not cp.get("ok"):
        return {"outcome": "miss", "reason": cp.get("reason", "unparseable_market"),
                "attempted": attempted, "detail": hit["slug"]}

    # Complementarity. False is a hard failure; None means the away series was
    # absent so the check could not run, which is recorded, not silently passed.
    if cp.get("complement_ok") is False:
        return {"outcome": "miss", "reason": "complementarity_failed",
                "attempted": attempted,
                "detail": f"{hit['slug']} sum={cp.get('complement_sum')}"}

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
        "n_pre_tipoff": cp["n_pre_tipoff"],
        "secs_before_tip": cp["secs_before_tip"],
        "stale_flat_run": cp.get("stale_flat_run"),
        "complement_sum": cp.get("complement_sum"),
        "complement_ok": cp.get("complement_ok"),
        "market_winner": cp.get("market_winner"),
        "label_agreement": agreement,
        "volume": _volume(market),
        "game_start_time": market.get("gameStartTime"),
    }
    return {"outcome": "priced", "row": row, "attempted": attempted}


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

    counts: dict[str, int] = {"priced": 0, "miss": 0}
    for i, g in enumerate(todo, 1):
        res = census_game(client, sport, g, abbr_map, labels)
        if res["outcome"] == "priced":
            store.put_priced(sport, season, g["game_id"], res["row"])
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


def reprobe_misses(client: Client, store: Store, tel: Telemetry, sport: str, season: str,
                   games: list[dict], abbr_map: dict[str, str], *,
                   reasons: tuple[str, ...] = ("no_market",)) -> dict:
    """E6 second pass: re-probe every `no_market` with the cache bypassed.

    An empty `/events?slug=` response is indistinguishable from a transient
    upstream failure, and the cache never stores an empty result precisely so
    this pass can be meaningful. A miss that survives a cache-bypassed re-probe
    is a real miss; one that does not was an artifact.
    """
    labels = team_labels(games)
    by_id = {g["game_id"]: g for g in games}
    rows = store.db.execute(
        f"SELECT game_id, reason FROM misses WHERE sport=? AND season=? "
        f"AND reason IN ({','.join('?' * len(reasons))})",
        [sport, season, *reasons]).fetchall()
    out = {"reprobed": 0, "recovered": 0, "still_missing": 0}
    for game_id, _reason in rows:
        g = by_id.get(game_id)
        if g is None:
            continue
        out["reprobed"] += 1
        res = census_game(client, sport, g, abbr_map, labels, bypass_cache=True)
        if res["outcome"] == "priced":
            store.put_priced(sport, season, game_id, res["row"])
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
