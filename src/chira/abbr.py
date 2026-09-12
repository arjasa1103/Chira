"""T3 — learn the per-season slug abbreviation map.

Why per season: the convention is NOT stable across seasons. `nba-lal-no-2023-12-07`
uses `no` for New Orleans where `nba-nop-lal-2025-11-30` uses `nop`. A map learned
once and reused silently misses whole teams in another season, and those misses are
indistinguishable from "no market exists".

Why this needs no league schedule: each market carries BOTH halves of the mapping.
The slug gives `<sport>-<away>-<home>-<ET date>` and `outcomes` gives the two team
nicknames, index-aligned to the same away/home order. So the map is derivable from
Polymarket alone, which is what makes it a week-1 task instead of a week-2 one.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, timedelta

from .http import Client

SLUG_RE = re.compile(r"^(nba|nhl)-([a-z0-9]+)-([a-z0-9]+)-(\d{4}-\d{2}-\d{2})$")

TEAM_COUNT = {"nba": 30, "nhl": 32}

# Regular season windows for the two usable seasons (2023-24 excluded: dead markets).
SEASON_SPANS = {
    "2024-25": (date(2024, 10, 15), date(2025, 4, 20)),
    "2025-26": (date(2025, 10, 1), date(2026, 4, 20)),
}


def _windows(span: tuple[date, date], n: int, days: int = 7) -> list[tuple[str, str]]:
    """n evenly spaced windows of `days` across the season span."""
    start, end = span
    total = (end - start).days
    step = max(1, (total - days) // max(1, n - 1))
    out = []
    for i in range(n):
        a = start + timedelta(days=i * step)
        if a >= end:
            break
        b = min(a + timedelta(days=days), end)
        out.append((a.isoformat() + "T00:00:00Z", b.isoformat() + "T00:00:00Z"))
    return out


def learn(client: Client, season: str, *, n_windows: int = 12,
          max_pages: int = 8, verbose: bool = True) -> dict:
    """Return {sport: {abbr: nickname}} plus conflicts and coverage for one season."""
    pairs: dict[str, dict[str, set]] = {"nba": defaultdict(set), "nhl": defaultdict(set)}
    order_ok = 0
    order_checked = 0
    seen_slugs: set[str] = set()

    for lo, hi in _windows(SEASON_SPANS[season], n_windows):
        for page in range(max_pages):
            rows = client.markets(limit=100, offset=page * 100,
                                  end_date_min=lo, end_date_max=hi)
            if not rows:
                break
            for m in rows:
                slug = m.get("slug") or ""
                mt = SLUG_RE.match(slug)
                if not mt or slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                sport, away_abbr, home_abbr, _ = mt.groups()
                try:
                    outs = json.loads(m.get("outcomes") or "[]")
                except (json.JSONDecodeError, TypeError):
                    continue
                if len(outs) != 2:
                    continue
                # outcomes are index-aligned to the slug's away/home order.
                pairs[sport][away_abbr].add(outs[0])
                pairs[sport][home_abbr].add(outs[1])
                order_checked += 1
                order_ok += 1
        if verbose:
            print(f"    {season} {lo[:10]}..{hi[:10]}  slugs so far: {len(seen_slugs)}", flush=True)

    result = {"season": season, "sports": {}, "conflicts": {}, "slugs_seen": len(seen_slugs)}
    for sport, m in pairs.items():
        clean, conflict = {}, {}
        for abbr, names in m.items():
            if len(names) == 1:
                clean[abbr] = next(iter(names))
            else:
                conflict[abbr] = sorted(names)
        result["sports"][sport] = dict(sorted(clean.items()))
        if conflict:
            result["conflicts"][sport] = conflict
    return result
