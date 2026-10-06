"""Chart 4: reliability diagrams, model beside market, on DEV (PLAN weeks 8-9).

    uv run python scripts/make_reliability.py

The last figure the writeup needs. PREREGISTRATION section 6 wants every table
and figure produced on dev before the holdout opens, so that opening it only
fills in numbers -- and a figure first drawn during the holdout pass is one
whose design was chosen with holdout data in view.

The model predictions are the out-of-sample rolling-origin ones (Amendment
5c), not in-sample fits, so the curve is comparable to the market's.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from chira.model import configure

configure()

import numpy as np

from chira.analysis import open_frame
from chira.charts import chart_reliability
from chira.holdout import DEV_SEASON
from chira.model import pooled, rolling_origin
from chira.prices import attach_game_prices
from chira.scoring import score_set

OUT_PNG = "docs/charts/chart4-reliability.png"
OUT_JSON = "docs/charts/reliability.json"

_ROWS_SQL = """
SELECT f.*, r.rating_diff_strength, r.p_home_elo, r.y, r.neutral_site, r.start_t
FROM read_parquet(?) f
JOIN read_parquet(?) r USING (sport, season, game_id)
WHERE f.season = ?
ORDER BY f.sport, f.game_id
"""


def rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--png", default=OUT_PNG)
    ap.add_argument("--json", default=OUT_JSON)
    ap.add_argument("--reps", type=int, default=2000)
    ap.add_argument("--horizon", default="close")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    snaps = sorted(glob.glob("data/snapshots/census-*"))
    if not args.snapshot and not snaps:
        print("no snapshot found")
        return 2
    con = open_frame(args.snapshot or snaps[-1], verify=not args.no_verify)
    attach_game_prices(con)
    data = rows(con.execute(_ROWS_SQL, ["data/features/features.parquet",
                                        "data/ratings/ratings.parquet",
                                        DEV_SEASON]))
    panels = []
    for sport in ("nba", "nhl"):
        sub = [r for r in data if r["sport"] == sport]
        t0 = time.time()
        folds = rolling_origin(sub, sport=sport)
        p, y, ids = pooled(folds)
        price = dict(con.execute("""
            SELECT game_id, p FROM game_prices
            WHERE sport = ? AND season = ? AND side = 'home' AND horizon = ?
        """, [sport, DEV_SEASON, args.horizon]).fetchall())
        keep = [i for i, g in enumerate(ids) if g in price]
        k = np.array(keep)
        pm = np.array([price[ids[i]] for i in keep], dtype=float)
        panels.append({"label": sport.upper(), "p_model": p[k],
                       "p_market": pm, "y": y[k]})
        print(f"{sport}: {len(folds)} folds in {time.time() - t0:.0f}s, "
              f"{len(ids):,} out-of-sample games, {len(keep):,} with a "
              f"{args.horizon} price")
        m = score_set(p[k], y[k], seasons=[DEV_SEASON] * k.size,
                      game_ids=[ids[i] for i in keep])
        q = score_set(pm, y[k], seasons=[DEV_SEASON] * k.size,
                      game_ids=[ids[i] for i in keep])
        print(f"   model  Brier {m.brier:.5f}  ECE {m.ece:.5f}")
        print(f"   market Brier {q.brier:.5f}  ECE {q.ece:.5f}")
        print(f"   deficit {m.brier - q.brier:+.5f} Brier "
              f"(Phase 5's pre-stated band is 0.02-0.03)")

    stats = chart_reliability(panels, args.png, reps=args.reps)

    def jsonable(o):
        """numpy arrays and scalars, which the curve dicts are full of."""
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.generic):
            return o.item()
        raise TypeError(f"not JSON serialisable: {type(o).__name__}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(
        json.dumps({"dev_season": DEV_SEASON, "horizon": args.horizon,
                    "reps": args.reps, "panels": stats},
                   indent=1, sort_keys=True, default=jsonable) + "\n",
        encoding="utf-8")
    print(f"\nwrote {args.png} and {args.json}")
    for label, s in stats.items():
        print(f"  {label}: {s['bins']} shared bins, "
              f"market slope {s['market']['cox_slope']:.3f}, "
              f"model slope {s['model']['cox_slope']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
