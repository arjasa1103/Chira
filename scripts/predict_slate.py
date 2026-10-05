"""Pre-game Elo odds for one night's NHL slate, logged before the games.

    uv run python scripts/predict_slate.py                 # tonight (ET)
    uv run python scripts/predict_slate.py --date 2026-10-04

**It never reads the target slate's results.** The Elo is walked over games
that STARTED strictly before the first game of the target date, and the
target games are taken from the schedule with their score fields ignored. So
the output is a forecast, not a dressed-up hindsight.

**That is not the same as the forecast being blind.** A slate whose games are
already over can be predicted without looking, but the results exist, so the
record is only as credible as the promise not to have looked. Run it BEFORE
puck drop and the log file is evidence; run it after and it is an exercise.
`blind` in the output says which one happened, by comparing the run time to
the first tipoff.

Appends to `data/predictions/slate-log.jsonl`, one line per game per run, so
a season of these accumulates into something with enough n to actually test
(~400 games by December, where 21 games resolves nothing).

The ratings are `ratings.CHOSEN`, frozen in d66671c and never re-tuned. This
script cannot change them, and nothing it prints may be used to.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, "src")
from chira.analysis import open_frame
from chira.cache import Cache
from chira.constants import NHL_API
from chira.http import Client
from chira.nhl import NHL_TEAMS, season_code
from chira.ratings import CHOSEN, expected_home, final_ratings, is_neutral

SEASON = "2026-27"
LOG = "data/predictions/slate-log.jsonl"
BURNIN = "data/burnin/burnin-2023-24.parquet"


def completed(client, season: str) -> list[dict]:
    """Every finished regular-season game, with scores. Rating input only."""
    by_id: dict[str, dict] = {}
    for t in NHL_TEAMS:
        p = client.get_json(
            f"{NHL_API}/club-schedule-season/{t}/{season_code(season)}",
            bypass_cache=True)
        for g in (p or {}).get("games", []):
            if g.get("gameType") != 2 or g.get("gameState") not in ("OFF", "FINAL"):
                continue
            ap = (g.get("awayTeam") or {}).get("score")
            hp = (g.get("homeTeam") or {}).get("score")
            if ap is None or hp is None:
                continue
            by_id[str(g["id"])] = {
                "sport": "nhl", "season": season, "game_id": str(g["id"]),
                "et_date": str(g.get("gameDate", ""))[:10],
                "away": g["awayTeam"]["abbrev"].lower(),
                "home": g["homeTeam"]["abbrev"].lower(),
                "away_pts": int(ap), "home_pts": int(hp),
                "winner": "home" if hp > ap else "away",
                "neutral_site": bool(g.get("neutralSite")),
                "start_t": int(datetime.fromisoformat(
                    g["startTimeUTC"].replace("Z", "+00:00")).timestamp())}
    return sorted(by_id.values(), key=lambda g: g["start_t"])


def slate(client, day: date) -> list[dict]:
    """The target date's games. **Score fields are not read.**"""
    payload = client.get_json(f"{NHL_API}/schedule/{day.isoformat()}",
                              bypass_cache=True)
    out = []
    for d in (payload or {}).get("gameWeek") or []:
        if str(d.get("date")) != day.isoformat():
            continue
        for g in d.get("games") or []:
            if g.get("gameType") != 2:
                continue
            out.append({
                "sport": "nhl", "season": SEASON, "game_id": str(g["id"]),
                "et_date": day.isoformat(),
                "away": g["awayTeam"]["abbrev"].lower(),
                "home": g["homeTeam"]["abbrev"].lower(),
                "neutral_site": bool(g.get("neutralSite")),
                "start_time_utc": g.get("startTimeUTC"),
                "start_t": int(datetime.fromisoformat(
                    g["startTimeUTC"].replace("Z", "+00:00")).timestamp())})
    return sorted(out, key=lambda g: (g["start_t"], g["game_id"]))


def history(con, burnin: str) -> list[dict]:
    cur = con.execute("""
      SELECT sport, season, game_id, et_date, away, home, away_pts, home_pts,
             winner, coalesce(neutral_site, FALSE) AS neutral_site,
             epoch(CAST(start_time_utc AS TIMESTAMPTZ))::BIGINT AS start_t
      FROM games WHERE sport = 'nhl'
      UNION ALL
      SELECT sport, season, game_id, et_date, away, home, away_pts, home_pts,
             winner, neutral_site,
             epoch(CAST(start_time_utc AS TIMESTAMPTZ))::BIGINT
      FROM read_parquet(?) WHERE sport = 'nhl'""", [burnin])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def first_blind(lines: list[dict]) -> tuple[dict[str, dict], int]:
    """The FIRST blind record per game, and how many rows were not blind.

    Pure, because this is the rule that matters: re-running a date appends,
    and grading the best of several bites would turn a forecast log into a
    selection of one. Non-blind rows never count at all.
    """
    first: dict[str, dict] = {}
    not_blind = 0
    for rec in sorted(lines, key=lambda r: r["logged_at"]):
        if not rec.get("blind"):
            not_blind += 1
            continue
        first.setdefault(rec["game_id"], rec)
    return first, not_blind


def grade(graded: list[tuple[dict, dict]]) -> dict:
    """Record, Brier and log loss over (forecast, final game) pairs."""
    import math

    n = len(graded)
    if not n:
        return {"n": 0}
    hit = home_hit = 0
    brier = ll = 0.0
    for rec, g in graded:
        y = 1.0 if g["winner"] == "home" else 0.0
        p = rec["p_home"]
        hit += int((y == 1.0) == (p >= 0.5))
        home_hit += int(y == 1.0)
        brier += (p - y) ** 2
        ll += -(y * math.log(max(p, 1e-12))
                + (1 - y) * math.log(max(1 - p, 1e-12)))
    return {"n": n, "hit": hit, "home_hit": home_hit,
            "accuracy": hit / n, "home_accuracy": home_hit / n,
            "brier": brier / n, "log_loss": ll / n,
            "expected_correct": sum(max(r["p_home"], 1 - r["p_home"])
                                    for r, _ in graded)}


def score_log(client, path: str) -> int:
    """Grade the logged forecasts. A SEPARATE act from making them."""
    lines = [json.loads(x) for x in Path(path).read_text(
        encoding="utf-8").splitlines() if x.strip()]
    first, not_blind = first_blind(lines)
    if not first:
        print(f"{path}: no blind records yet "
              f"({not_blind} non-blind rows ignored)")
        return 0
    done = {g["game_id"]: g for g in completed(client, SEASON)}
    pairs = [(rec, done[gid]) for gid, rec in first.items() if gid in done]
    print(f"{path}: {len(first)} blind forecasts, {len(pairs)} with a final "
          f"score ({not_blind} non-blind rows ignored)")
    g = grade(pairs)
    if not g["n"]:
        return 0
    print(f"  Elo lean correct   {g['hit']}/{g['n']} = {g['accuracy']:.1%}")
    print(f"  always pick home   {g['home_hit']}/{g['n']} = "
          f"{g['home_accuracy']:.1%}")
    print(f"  Brier {g['brier']:.5f}   log loss {g['log_loss']:.5f}")
    print(f"  expected correct from the forecasts themselves: "
          f"{g['expected_correct']:.1f}")
    print("\n  n is what makes this readable. At 21 games the 95% "
          "interval spans a coin flip to the dev rate; ~200 games is "
          "where it starts to resolve anything.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="ET date; default today")
    ap.add_argument("--score", action="store_true",
                    help="grade the log instead of adding to it")
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--burnin", default=BURNIN)
    ap.add_argument("--log", default=LOG)
    ap.add_argument("--no-log", action="store_true")
    args = ap.parse_args()

    if args.score:
        return score_log(
            Client(cache=Cache(".http-cache", abbr_version="predict")),
            args.log)

    snaps = sorted(glob.glob("data/snapshots/census-*"))
    if not snaps and not args.snapshot:
        print("no snapshot found")
        return 2
    day = (date.fromisoformat(args.date) if args.date
           else datetime.now(UTC).astimezone().date())
    client = Client(cache=Cache(".http-cache", abbr_version="predict"))

    games = slate(client, day)
    if not games:
        print(f"no regular-season NHL games on {day}")
        return 0
    first_tip = min(g["start_t"] for g in games)
    now = int(datetime.now(UTC).timestamp())
    blind = now < first_tip

    con = open_frame(args.snapshot or snaps[-1], verify=False)
    past = [g for g in completed(client, SEASON) if g["start_t"] < first_tip]
    walk = history(con, args.burnin) + past
    r = final_ratings(walk, **CHOSEN["nhl"])
    H = CHOSEN["nhl"]["h"]

    print(f"NHL slate for {day} (ET) — {len(games)} games")
    print(f"ratings from {len(walk):,} games that started before the first "
          f"tipoff ({len(past)} of them in {SEASON})")
    print(f"constants: K={CHOSEN['nhl']['k']} H={H} "
          f"c={CHOSEN['nhl']['c']} (frozen, d66671c)")
    print(f"BLIND: {blind}  "
          + ("(run before puck drop; this log is evidence)" if blind else
             "(run after the games; the results already exist, so this is an "
             "exercise, not a test)"))
    print()
    print("  tipoff (UTC)       away @ home    elo_away  elo_home   P(home)  "
          "P(away)  lean")
    records = []
    for g in games:
        a, h = g["away"], g["home"]
        ra = r.get(f"nhl:{a}", 1500.0)
        rh = r.get(f"nhl:{h}", 1500.0)
        hb = 0.0 if is_neutral(g) else float(H)
        p = expected_home(rh, ra, hb)
        lean = h.upper() if p >= 0.5 else a.upper()
        print(f"  {g['start_time_utc'][:16]}  {a:>4} @ {h:<5}   "
              f"{ra:8.1f}  {rh:8.1f}   {p:6.3f}   {1 - p:6.3f}  "
              f"{lean} {max(p, 1 - p):.1%}")
        records.append({
            "logged_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "blind": blind, "et_date": g["et_date"],
            "game_id": g["game_id"], "away": a, "home": h,
            "start_time_utc": g["start_time_utc"],
            "elo_away": round(ra, 2), "elo_home": round(rh, 2),
            "home_bonus": hb, "p_home": round(p, 6),
            "lean": lean, "confidence": round(max(p, 1 - p), 6),
            "constants": CHOSEN["nhl"],
            "rating_games": len(walk)})

    if not args.no_log:
        p = Path(args.log)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
        print(f"\nappended {len(records)} rows to {args.log}")
    print("\nNo result for these games was read. Scoring is a separate step, "
          "and 21 games resolves nothing: the point of the log is the n it "
          "reaches by December.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
