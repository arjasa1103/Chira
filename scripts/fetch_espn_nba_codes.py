"""Re-derive the ESPN -> census NBA abbreviation map and diff it.

    uv run python scripts/fetch_espn_nba_codes.py

`upcoming.ESPN_TO_CENSUS` is vendored, for the reason the venue table and the
neutral-site list are vendored: a translation table fetched at run time can
change under the collector mid-season, and the failure is silent -- a drifted
code resolves no market and the day looks like "Polymarket had not listed it".
This script is the check that the vendored table still matches the source.

Exits non-zero on any disagreement, and prints the 30 ESPN codes beside the
30 the census uses so a real rename is a one-line edit rather than a guess.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from chira.constants import ESPN_NBA_API
from chira.http import Client
from chira.upcoming import ESPN_TO_CENSUS

ABBR_PATH = "data/abbr_map_resolved.json"


def census_codes(path: str = ABBR_PATH) -> set[str]:
    """The 30 lowercase codes the census and the collector slug with."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    for season in sorted((doc.get("seasons") or {}), reverse=True):
        nba = (doc["seasons"][season] or {}).get("nba") or {}
        codes = set((nba.get("map") or {}).values())
        if codes:
            return codes
    raise SystemExit(f"no NBA codes in {path}")


def espn_codes(client: Client) -> dict[str, str]:
    """{lowercased ESPN abbreviation: display name} for all 30 teams."""
    payload = client.get_json(f"{ESPN_NBA_API}/teams")
    teams = payload["sports"][0]["leagues"][0]["teams"]
    out = {}
    for row in teams:
        team = row["team"]
        out[str(team["abbreviation"]).lower()] = str(team.get("displayName"))
    return out


def main() -> int:
    want = census_codes()
    got = espn_codes(Client())
    print(f"census codes: {len(want)}   ESPN teams: {len(got)}")

    problems = []
    if len(got) != 30:
        problems.append(f"ESPN returned {len(got)} teams, expected 30")

    translated = {}
    for code, name in sorted(got.items()):
        mapped = ESPN_TO_CENSUS.get(code, code)
        translated[mapped] = code
        flag = "" if mapped in want else "  <-- NOT A CENSUS CODE"
        arrow = "==" if mapped == code else "->"
        if flag:
            problems.append(f"ESPN {code!r} ({name}) maps to {mapped!r}, "
                            f"which the census does not use")
        print(f"  {code:5} {arrow} {mapped:5}  {name}{flag}")

    missing = want - set(translated)
    if missing:
        problems.append(f"census codes with no ESPN source: {sorted(missing)}")

    stale = sorted(k for k in ESPN_TO_CENSUS if k not in got)
    if stale:
        problems.append(f"ESPN_TO_CENSUS has entries ESPN no longer uses: "
                        f"{stale}")

    if problems:
        print("\nDISAGREEMENT:")
        for p in problems:
            print(f"  - {p}")
        print("\nFix upcoming.ESPN_TO_CENSUS; do not make it dynamic.")
        return 1
    print(f"\nok: all 30 ESPN codes translate into census codes "
          f"({len(ESPN_TO_CENSUS)} need translating, "
          f"{30 - len(ESPN_TO_CENSUS)} are identical)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
