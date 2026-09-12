"""Resolve schedule abbreviations to slug abbreviations, per sport, per season.

This closes the gap the week-1 learner left. `abbr.learn()` mines Polymarket by
paginating Gamma, and Gamma's offset ceiling made it return 0/30 NBA teams for
2025-26 while finding 32/32 NHL from identical windows. It also produced the
WRONG DIRECTION of map -- `{slug_abbr: nickname}`, where slug construction needs
`{schedule_abbr: slug_abbr}` -- so `data/abbr_map.json` was read by no code at
all. It is a PRIOR into this module and nothing else.

Resolution is driven from the league schedule, the same rule the census
follows, and every mapping is CONFIRMED against the market's own `outcomes`
labels rather than accepted because a slug returned 200. A slug can hit and
still be the wrong game, and an unconfirmed hit is not a mapping.

Three things here were each learned by a failed run, not designed up front:

1. **Probe mid-season, not in date order.** Date order resolved 0/32 NHL teams
   for 2024-25: the whole attempt budget went to early-October games, and
   Polymarket's NHL coverage does not start at the season opener.
2. **Match the place name as well as the nickname.** Utah's NHL `commonName` is
   'Utah Hockey Club' in 2024-25 and 'Mammoth' in 2025-26, while the market
   labels that team "Utah" in both. Nickname-only matching resolved Utah in one
   season and missed it in the other.
3. **Only an unresolved side spends attempt budget.** Charging a resolved
   opponent starved teams whose games all faced already-confirmed opponents.

Budget: roughly 20-40 `/events?slug=` calls per sport-season, against a
~7,400-request census.
"""

from __future__ import annotations

import json
import re
from datetime import date

from .http import Client
from .schedule import slug_candidates

_NORM = re.compile(r"[^a-z0-9]+")


def normalize_nickname(name: str) -> str:
    return _NORM.sub("", (name or "").lower())


def label_match(schedule_labels: tuple[str, ...] | list[str], market_name: str) -> bool:
    """True if any schedule label loosely matches the market's outcome label.

    Loose (substring either way) rather than exact, because the market label is
    a human-chosen team name that is sometimes the mascot and sometimes the
    city. Ambiguous place names are filtered out by the caller, not here.
    """
    b = normalize_nickname(market_name)
    if not b:
        return False
    return any(a and (a in b or b in a)
               for a in (normalize_nickname(x) for x in schedule_labels))


def team_labels(games: list[dict]) -> dict[str, tuple[str, ...]]:
    """{schedule_abbr: (labels to match on)} for one sport-season.

    The nickname is always included. The place name is included ONLY if it is
    unique in the league: 'Los Angeles' covers both LAL and LAC, and accepting
    a place-level match there would let the resolver confirm a Lakers/Clippers
    slug with the two sides SWAPPED. An orientation flip does not crash, it
    mirrors the calibration curve about 0.5, so this is the one place where a
    loose match has to be tightened.
    """
    nicks: dict[str, str] = {}
    places: dict[str, str] = {}
    for g in games:
        for side in ("away", "home"):
            nicks[g[side]] = g.get(f"{side}_name", "")
            places[g[side]] = g.get(f"{side}_place", "")
    counts: dict[str, int] = {}
    for place in places.values():
        key = normalize_nickname(place)
        counts[key] = counts.get(key, 0) + 1
    out = {}
    for abbr, nick in nicks.items():
        labels = [nick]
        place = places.get(abbr, "")
        if place and counts.get(normalize_nickname(place), 0) == 1:
            labels.append(place)
        out[abbr] = tuple(x for x in labels if x)
    return out


def invert_learned(learned: dict, sport: str, season: str) -> dict[str, str]:
    """{normalized label: slug_abbr} from a learn() map, for one sport-season.

    Drops any label claimed by two slug abbreviations: an ambiguous prior is
    worse than no prior, because it sends the probe after the wrong team.
    """
    table = ((learned.get(season) or {}).get("sports") or {}).get(sport) or {}
    seen: dict[str, set[str]] = {}
    for abbr, nickname in table.items():
        seen.setdefault(normalize_nickname(nickname), set()).add(abbr)
    return {nick: next(iter(abbrs)) for nick, abbrs in seen.items() if len(abbrs) == 1}


def prior_lookup(prior: dict[str, str], labels: tuple[str, ...] | list[str]) -> str | None:
    """Find a prior entry for any of this team's labels, loosely. Longest wins."""
    best: tuple[str, str] | None = None
    for label in labels:
        nick = normalize_nickname(label)
        if not nick:
            continue
        for key, abbr in prior.items():
            if (key and (key in nick or nick in key)
                    and (best is None or len(key) > len(best[0]))):
                best = (key, abbr)
    return best[1] if best else None


def candidates(sched_abbr: str, labels: tuple[str, ...],
               priors: list[dict[str, str]]) -> list[str]:
    """Slug-abbreviation guesses for one team, best first, deduped.

    Order matters: a learned prior beats the identity guess, and the shortened
    forms come last because they are the ones that can collide with another
    team. Confirmed irregulars from the design doc: `sj` not `sjs`, `mon` not
    `mtl`, `cal` not `cgy`, `tb` not `tbl`, bare `utah`, `no` not `nop` in
    2023-24.
    """
    out: list[str] = []
    for prior in priors:
        hit = prior_lookup(prior, labels)
        if hit:
            out.append(hit)
    out.append(sched_abbr)
    out.append(sched_abbr[:2])
    for label in labels:
        nick = normalize_nickname(label)
        if nick:
            out.append(nick[:4])
            out.append(nick)
    return list(dict.fromkeys(c for c in out if c))


def probe_order(games: list[dict]) -> list[dict]:
    """Mid-season games first, deterministically. See module docstring item 1."""
    if not games:
        return []
    dates = sorted(g["et_date"] for g in games)
    mid = _ord(dates[len(dates) // 2])
    return sorted(games, key=lambda g: (abs(_ord(g["et_date"]) - mid), g["game_id"]))


def _ord(iso: str) -> int:
    return date.fromisoformat(iso[:10]).toordinal()


def _outcomes(market: dict) -> list | None:
    outs = market.get("outcomes")
    if isinstance(outs, str):
        try:
            outs = json.loads(outs)
        except (ValueError, TypeError):
            return None
    return outs if isinstance(outs, list) and len(outs) == 2 else None


def confirm(client: Client, sport: str, game: dict, away: str, home: str,
            labels: dict[str, tuple[str, ...]], *,
            bypass_cache: bool = False) -> dict:
    """Probe every date convention for one (away, home) pair; confirm by label.

    Always returns a dict carrying `attempted` (every slug tried, in order) so a
    miss can be classified as "no market exists" rather than "we never tried the
    right slug". `market` is None when nothing confirmed.

    Both sides must match in the away-then-home order the slug asserts. That
    ordering check is not decoration: a swap does not crash, it mirrors the
    calibration curve about 0.5 and looks like a finding.
    """
    attempted: list[str] = []
    probe = dict(game, away=away, home=home)
    for convention, cand in slug_candidates(sport, probe):
        attempted.append(cand)
        for ev in client.event_by_slug(cand, bypass_cache=bypass_cache) or []:
            for market in (ev.get("markets") or []):
                outs = _outcomes(market)
                if not outs:
                    continue
                if (label_match(labels[game["away"]], outs[0])
                        and label_match(labels[game["home"]], outs[1])):
                    return {"slug": cand, "convention": convention,
                            "market": market, "attempted": attempted}
    return {"slug": None, "convention": None, "market": None, "attempted": attempted}


def resolve(client: Client, sport: str, games: list[dict], priors: list[dict[str, str]],
            *, max_probes_per_team: int = 8, verbose: bool = False) -> dict:
    """Return {'map', 'unresolved', 'probes', 'evidence'} for one sport-season.

    Two passes, because the first probe of a season has no confirmed team to
    lean on: both sides are guesses, so a miss is ambiguous about WHICH side
    was wrong. Pass 1 takes the cheap win (both top candidates correct confirms
    two teams at once). Pass 2 probes only games where exactly one side is
    still unresolved, so a hit attributes unambiguously.
    """
    labels = team_labels(games)
    cand = {t: candidates(t, labels[t], priors) for t in labels}
    ordered = probe_order(games)

    resolved: dict[str, str] = {}
    evidence: dict[str, dict] = {}
    attempts: dict[str, int] = dict.fromkeys(labels, 0)
    probes = 0

    def record(team: str, slug_abbr: str, hit: dict) -> None:
        resolved[team] = slug_abbr
        evidence.setdefault(team, {"slug": hit["slug"], "convention": hit["convention"]})

    for g in ordered:
        if len(resolved) == len(labels):
            break
        a, h = g["away"], g["home"]
        if a in resolved and h in resolved:
            continue
        if any(attempts[s] >= max_probes_per_team for s in (a, h) if s not in resolved):
            continue
        for side in (a, h):
            if side not in resolved:
                attempts[side] += 1
        probes += 1
        hit = confirm(client, sport, g, resolved.get(a, cand[a][0]),
                      resolved.get(h, cand[h][0]), labels)
        if hit["market"]:
            record(a, resolved.get(a, cand[a][0]), hit)
            record(h, resolved.get(h, cand[h][0]), hit)
            if verbose:
                print(f"    pass1 {hit['slug']} ({hit['convention']})", flush=True)

    for team in [t for t in labels if t not in resolved]:
        budget = max_probes_per_team * 2
        for g in ordered:
            if team in resolved or attempts[team] >= budget:
                break
            if team not in (g["away"], g["home"]):
                continue
            other = g["home"] if g["away"] == team else g["away"]
            if other not in resolved:
                continue
            for guess in cand[team]:
                if attempts[team] >= budget:
                    break
                attempts[team] += 1
                probes += 1
                hit = confirm(client, sport, g,
                              guess if g["away"] == team else resolved[other],
                              guess if g["home"] == team else resolved[other],
                              labels)
                if hit["market"]:
                    record(team, guess, hit)
                    if verbose:
                        print(f"    pass2 {team} -> {guess}  {hit['slug']}", flush=True)
                    break

    return {
        "map": dict(sorted(resolved.items())),
        "unresolved": sorted(t for t in labels if t not in resolved),
        "probes": probes,
        "evidence": evidence,
    }
