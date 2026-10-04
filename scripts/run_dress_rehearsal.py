"""The full dress rehearsal on dev (PLAN weeks 8-9).

    uv run python scripts/run_dress_rehearsal.py

PREREGISTRATION section 6: *"A full dress rehearsal on dev must first produce
every table and figure that will appear in the writeup, so opening the
holdout only fills in numbers."* This is that run. Every number here is
2024-25; the sealed 2025-26 season is never read, and the scoring path would
refuse it anyway (`holdout.assert_scorable`).

What it produces, in order:

1. The rolling-origin evaluation (Amendment 5c), per fold and pooled.
2. Model against the Elo and against the base rate, Brier primary.
3. The GBM ceiling (T17): what interpretability costs, as a number.
4. The hyperprior sensitivity analysis (section 5), and whether any variance
   parameter is prior-driven.
5. Section 9's risk tiers on the model-market edge, with game-level
   intervals, plus an exploratory reliability table by probability bucket.
6. The nested test (section 7) rehearsed on dev, OUT OF SAMPLE per rolling-
   origin fold: Clark-West against both nulls, under both closing-price
   constructions, with Model B on the model's own covariates.

Output lands in `data/rehearsal/` as JSON, so week 9's holdout pass fills the
same shapes.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, "src")
from chira.model import configure

configure()

import numpy as np

from chira.analysis import open_frame
from chira.ceiling import (
    GBM_KW,
    pooled_ceiling,
    rolling_origin_ceiling,
)
from chira.holdout import DEV_SEASON
from chira.model import (
    ROLLING_ORIGINS,
    hyperprior_sensitivity,
    pooled,
    prior_driven,
    rolling_origin,
)
from chira.prices import attach_game_prices
from chira.scoring import (
    clark_west,
    pooled_nested,
    reliability_buckets,
    risk_tiers,
    rolling_nested,
    score_set,
)

OUT = "data/rehearsal"
# Section 7: the nested test runs under two closing-price constructions that
# actually differ, because a gain existing only under one is measurement
# error in the benchmark.
PRICE_LOOKS = ("close", "t1h")

_ROWS_SQL = """
SELECT f.*, r.rating_diff_strength, r.p_home_elo, r.y, r.neutral_site,
       r.start_t, g.et_date AS game_date
FROM read_parquet(?) f
JOIN read_parquet(?) r USING (sport, season, game_id)
JOIN games g USING (sport, season, game_id)
WHERE f.season = ?
ORDER BY f.sport, f.game_id
"""


def rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def market_prices(con, sport: str, horizon: str) -> dict[str, float]:
    got = con.execute("""
        SELECT game_id, p FROM game_prices
        WHERE sport = ? AND season = ? AND side = 'home' AND horizon = ?
    """, [sport, DEV_SEASON, horizon]).fetchall()
    return {g: float(p) for g, p in got}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--sports", nargs="*", default=["nba", "nhl"])
    ap.add_argument("--reps", type=int, default=2000)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--skip-sensitivity", action="store_true",
                    help="the sensitivity refits six times per sport")
    args = ap.parse_args()

    snaps = sorted(glob.glob("data/snapshots/census-*"))
    if not args.snapshot and not snaps:
        print("no snapshot found; run scripts/make_snapshot.py first")
        return 2
    snap = args.snapshot or snaps[-1]
    con = open_frame(snap, verify=not args.no_verify)
    attach_game_prices(con)
    data = rows(con.execute(_ROWS_SQL, ["data/features/features.parquet",
                                        "data/ratings/ratings.parquet",
                                        DEV_SEASON]))
    print(f"snapshot: {snap}\ndev rows: {len(data):,} ({DEV_SEASON} only)")
    Path(args.out).mkdir(parents=True, exist_ok=True)
    report: dict = {"dev_season": DEV_SEASON, "origins": list(ROLLING_ORIGINS),
                    "sports": {}}

    for sport in args.sports:
        sub = [r for r in data if r["sport"] == sport]
        s_out: dict = {"n": len(sub)}
        print(f"\n{'=' * 68}\n{sport.upper()}  —  {len(sub):,} dev games\n"
              f"{'=' * 68}")

        # 1-2. rolling origin, and what it beats
        t0 = time.time()
        folds = rolling_origin(sub, sport=sport)
        p, y, ids = pooled(folds)
        print(f"\n1. ROLLING ORIGIN ({len(folds)} folds, "
              f"{time.time() - t0:.0f}s)")
        print("   origin       train  test   Brier   log loss  div  R-hat")
        for f in folds:
            s = score_set(f.p, f.y, seasons=[DEV_SEASON] * f.n_test,
                          game_ids=f.game_ids)
            print(f"   {f.origin}  {f.n_train:>5}  {f.n_test:>4}  "
                  f"{s.brier:.5f}  {s.log_loss:.5f}  {f.diag.divergences:>3}  "
                  f"{f.diag.max_rhat:.4f}")
        seasons = [DEV_SEASON] * len(p)
        model_s = score_set(p, y, seasons=seasons, game_ids=ids)
        elo_map = {r["game_id"]: r["p_home_elo"] for r in sub}
        elo_p = np.array([elo_map[g] for g in ids])
        elo_s = score_set(elo_p, y, seasons=seasons, game_ids=ids)
        base_p = np.full_like(y, float(np.mean(y)))
        base_s = score_set(base_p, y, seasons=seasons, game_ids=ids)
        print(f"\n2. OUT OF SAMPLE, pooled over folds (n={len(p):,})")
        for label, sc in (("model    ", model_s), ("elo alone", elo_s),
                          ("base rate", base_s)):
            print(f"   {label}  Brier {sc.brier:.5f}   log loss "
                  f"{sc.log_loss:.5f}   ECE {sc.ece:.5f}")
        print(f"   model - elo:  Brier {model_s.brier - elo_s.brier:+.5f}, "
              f"log loss {model_s.log_loss - elo_s.log_loss:+.5f}")
        s_out["rolling_origin"] = {
            "folds": [{"origin": f.origin, "n_train": f.n_train,
                       "n_test": f.n_test,
                       "divergences": f.diag.divergences,
                       "max_rhat": f.diag.max_rhat} for f in folds],
            "model": asdict(model_s), "elo": asdict(elo_s),
            "base_rate": asdict(base_s)}

        # 3. the ceiling
        t0 = time.time()
        cf = rolling_origin_ceiling(sub, sport=sport)
        gp, gy, gids = pooled_ceiling(cf)
        gbm_s = score_set(gp, gy, seasons=[DEV_SEASON] * len(gp),
                          game_ids=gids)
        print(f"\n3. GBM CEILING (T17, {time.time() - t0:.0f}s, "
              f"same folds, same covariates)")
        print(f"   gbm        Brier {gbm_s.brier:.5f}   log loss "
              f"{gbm_s.log_loss:.5f}")
        print(f"   THE COST OF INTERPRETABILITY: "
              f"{model_s.brier - gbm_s.brier:+.5f} Brier, "
              f"{model_s.log_loss - gbm_s.log_loss:+.5f} log loss")
        print("   (positive means the black box is better; it is reported, "
              "never shipped)")
        s_out["ceiling"] = {"gbm": asdict(gbm_s), "gbm_kw": GBM_KW,
                            "brier_cost": model_s.brier - gbm_s.brier,
                            "log_loss_cost":
                                model_s.log_loss - gbm_s.log_loss}

        # 4. hyperprior sensitivity
        if not args.skip_sensitivity:
            t0 = time.time()
            sens = hyperprior_sensitivity(sub, sport=sport)
            print(f"\n4. HYPERPRIOR SENSITIVITY (section 5, "
                  f"{time.time() - t0:.0f}s)")
            for r in sens:
                print(r.line())
            flags = prior_driven(sens)
            for f in flags:
                print(f"   PRIOR-DRIVEN: {f}")
            if not flags:
                print("   no variance parameter tracks its prior; the data "
                      "carries them")
            s_out["sensitivity"] = {
                "rows": [{k: v for k, v in asdict(r).items() if k != "diag"}
                         for r in sens], "prior_driven": flags}

        # 5. risk tiers, as section 9 defines them: the edge between the
        # model and the market's closing price (section 2's construction).
        close = market_prices(con, sport, "close")
        keep = [i for i, g in enumerate(ids) if g in close]
        k = np.array(keep)
        tiers, untiered = risk_tiers(p[k], np.array([close[ids[i]] for i in keep]),
                                     y[k], reps=args.reps)
        print(f"\n5. RISK TIERS (section 9: |p_model - p_market| at the close, "
              f"out of sample, n={len(keep):,}; {untiered:,} under the 0.02 "
              f"floor, not tiered)")
        for t in tiers:
            print(t.line())
        buckets = reliability_buckets(p, y, reps=args.reps)
        print("   reliability by model-probability bucket (exploratory, "
              "NOT section 9):")
        for t in buckets:
            print(t.line())
        s_out["risk_tiers"] = {"tiers": [asdict(t) for t in tiers],
                               "untiered": untiered, "n_priced": len(keep)}
        s_out["reliability_buckets"] = [asdict(t) for t in buckets]

        # 6. the nested test, rehearsed OUT OF SAMPLE: B and the recalibration
        # null are fitted per fold on that fold's training games, exactly as
        # the model is, and scored on the month after.
        print("\n6. NESTED TEST rehearsed on dev (section 7), out of sample "
              "per fold, Model B on the model's own covariates")
        date_of = {r["game_id"]: r["game_date"] for r in sub}
        s_out["nested"] = {}
        for horizon in PRICE_LOOKS:
            prices = market_prices(con, sport, horizon)
            nfolds, skipped = rolling_nested(sub, prices, sport=sport)
            preds, ny, nids = pooled_nested(nfolds)
            dates = np.array([date_of[g] for g in nids], dtype=str)
            print(f"   --- closing construction: {horizon} "
                  f"(n={len(nids):,} out of sample, {len(nfolds)} folds"
                  + (f"; skipped {', '.join(skipped)}: no priced games on one "
                     f"side" if skipped else "") + ")")
            s_out["nested"].setdefault(horizon, {})["skipped_origins"] = skipped
            for null in ("identity", "recalibrated"):
                cw = clark_west(ny, preds[null], preds["b"], dates=dates,
                                reps=args.reps)
                print("   " + cw.lines(f"B vs {null}")[0])
                s_out["nested"].setdefault(horizon, {})[null] = asdict(cw)

        report["sports"][sport] = s_out

    path = Path(args.out) / "dress-rehearsal.json"
    path.write_text(json.dumps(report, indent=1, sort_keys=True, default=str)
                    + "\n", encoding="utf-8")
    print(f"\nwrote {path}")
    print("\nEVERY NUMBER ABOVE IS DEV. The holdout has not been opened; "
          "week 9 fills these same shapes once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
