"""The single pass over the sealed 2025-26 holdout (PREREGISTRATION section 6).

    uv run python scripts/run_holdout.py                  # readiness report
    uv run python scripts/run_holdout.py --open-the-seal --reason "..."

**This is the one irreversible act in the project.** Section 6: the holdout is
opened exactly once, after the model is frozen by commit, and a full dress
rehearsal on dev must first have produced every table and figure, so that
opening it only fills in numbers. `holdout.open_holdout` enforces what it can
-- clean tree, HEAD on the remote, no marker here or on the remote, and the
marker committed AND pushed before a single label is returned.

**The default is a dry run.** It checks every precondition, prints what is
missing, and reads nothing from 2025-26. Breaking the seal takes an explicit
`--open-the-seal` and a `--reason` that goes into the permanent marker.

What the real run produces, in the same shapes the rehearsal produced on dev
(`data/rehearsal/dress-rehearsal.json`, `notes/week8-model.md`):

1. Model, market, Elo and base-rate scores on 2025-26.
2. The reliability figure, redrawn by the same function as chart 4.
3. Risk tiers.
4. The nested test: Clark-West against both nulls, under both closing-price
   constructions.

Nothing here chooses anything. Every parameter, every scaler, every fill
median and every bin rule comes from dev.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from chira.model import configure

configure()

import numpy as np

from chira.analysis import open_frame
from chira.charts import chart_reliability
from chira.holdout import (
    DEV_SEASON,
    HOLDOUT_SEASON,
    MARKER,
    HoldoutError,
    head_commit,
    is_clean,
    is_pushed,
    marker_on_remote,
    marker_path,
    open_holdout,
)
from chira.model import (
    build_design,
    dev_medians,
    fit,
    predict,
)
from chira.prices import attach_game_prices
from chira.scoring import (
    apply_nested,
    clark_west,
    fit_nested,
    risk_tiers,
    score_set,
)

OUT = "data/holdout"
PNG = "docs/charts/chart5-holdout-reliability.png"
PRICE_LOOKS = ("close", "t1h")

# The dev artefacts section 6 requires to exist BEFORE the seal breaks.
REQUIRED_DEV_ARTEFACTS = (
    ("data/rehearsal/dress-rehearsal.json", "the dress rehearsal's tables"),
    ("docs/charts/chart4-reliability.png", "the reliability figure"),
    ("data/features/features.parquet", "the feature store"),
    ("data/ratings/ratings.parquet", "the Elo walk"),
)

_ROWS_SQL = """
SELECT f.*, r.rating_diff_strength, r.p_home_elo, r.y, r.neutral_site, r.start_t,
       g.et_date AS game_date
FROM read_parquet(?) f
JOIN read_parquet(?) r USING (sport, season, game_id)
JOIN games g USING (sport, season, game_id)
WHERE f.season = ?
ORDER BY f.sport, f.game_id
"""


def rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def readiness(repo: str = ".") -> tuple[bool, list[str]]:
    """Every precondition, with the blockers named. Reads no holdout data."""
    blockers: list[str] = []
    ok_lines: list[str] = []

    for path, what in REQUIRED_DEV_ARTEFACTS:
        if Path(path).is_file() or Path(path).is_dir():
            ok_lines.append(f"  ok      {what} ({path})")
        else:
            blockers.append(f"missing {what}: {path}")

    if marker_path(repo).is_file():
        blockers.append(f"{MARKER} already exists here: the holdout is open")
    else:
        ok_lines.append(f"  ok      no local {MARKER}")

    if is_clean(repo):
        ok_lines.append("  ok      working tree is clean")
    else:
        blockers.append("working tree is dirty; the marker records a commit "
                        "hash and that record is the freeze")

    try:
        if is_pushed(repo):
            ok_lines.append(f"  ok      HEAD ({head_commit(repo)[:12]}) is on "
                            f"the remote")
        else:
            blockers.append("HEAD is not on the remote; a freeze only the "
                            "author can see is not a freeze")
    except HoldoutError as e:
        blockers.append(f"cannot check the remote: {e}")

    try:
        if marker_on_remote(repo):
            blockers.append(f"{MARKER} is on the remote: the holdout was "
                            f"already opened")
        else:
            ok_lines.append(f"  ok      no {MARKER} on the remote")
    except HoldoutError as e:
        blockers.append(f"cannot read the remote marker: {e}")

    for line in ok_lines:
        print(line)
    return not blockers, blockers


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open-the-seal", action="store_true",
                    help="actually break the seal. Once, ever.")
    ap.add_argument("--reason", default=None,
                    help="goes into the permanent marker")
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--png", default=PNG)
    ap.add_argument("--reps", type=int, default=2000)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    print(f"=== HOLDOUT READINESS ({HOLDOUT_SEASON}, sealed) ===")
    ready, blockers = readiness()
    if blockers:
        print("\n  BLOCKED:")
        for b in blockers:
            print(f"    - {b}")

    print("\n=== THINGS NO SCRIPT CAN CHECK ===")
    print("  These are in TODOS.md as P1 'before the holdout opens':")
    print("    - headline 1's framing, decided and written down")
    print("    - the NHL [0.35, 0.45) bucket: fix with an amendment, or")
    print("      state it as a known limitation. Not silently.")
    print("    - the Elo overlap (P2): refitting K/H/c inside each fold would")
    print("      change what 'the model beats the rating' means")
    print("  The seal is opened once. Anything undecided now is decided with")
    print("  the holdout in view, which is what section 6 exists to prevent.")

    if not args.open_the_seal:
        print(f"\nDRY RUN. Nothing from {HOLDOUT_SEASON} was read.")
        print("To break the seal: --open-the-seal --reason \"...\"")
        return 0 if ready else 1

    if not ready:
        print("\nrefusing to open the seal with blockers outstanding")
        return 1
    if not args.reason or not args.reason.strip():
        print("\n--reason is required: the marker has to say which frozen "
              "model this single pass was for")
        return 2

    snaps = sorted(glob.glob("data/snapshots/census-*"))
    con = open_frame(args.snapshot or snaps[-1], verify=not args.no_verify)
    attach_game_prices(con)

    # THE SEAL. Everything after this line is a second look if re-run.
    labels = open_holdout(con, reason=args.reason.strip())
    print(f"\n=== SEAL OPENED: {len(labels):,} {HOLDOUT_SEASON} labels "
          f"released ===")
    print(f"  marker committed and pushed; see {MARKER}")

    dev = rows(con.execute(_ROWS_SQL, ["data/features/features.parquet",
                                       "data/ratings/ratings.parquet",
                                       DEV_SEASON]))
    hold = rows(con.execute(_ROWS_SQL, ["data/features/features.parquet",
                                        "data/ratings/ratings.parquet",
                                        HOLDOUT_SEASON]))
    report: dict = {"holdout_season": HOLDOUT_SEASON, "sports": {}}
    panels = []

    for sport in ("nba", "nhl"):
        d_rows = [r for r in dev if r["sport"] == sport]
        h_rows = [r for r in hold if r["sport"] == sport]
        med = dev_medians(d_rows)
        d_design = build_design(d_rows, sport=sport, medians=med)
        f = fit(d_rows, sport=sport, design=d_design)
        h_design = build_design(h_rows, sport=sport, scaler=d_design.scaler,
                                medians=med)
        pred = predict(f, h_design)
        print(f"\n{sport.upper()}  n={h_design.n:,}")
        for line in pred.lines():
            print("  " + line)

        ids = list(h_design.game_ids)
        seasons = [HOLDOUT_SEASON] * len(ids)
        y = h_design.y
        elo = {r["game_id"]: r["p_home_elo"] for r in h_rows}
        price = dict(con.execute("""
            SELECT game_id, p FROM game_prices WHERE sport = ? AND season = ?
              AND side = 'home' AND horizon = 'close'""",
            [sport, HOLDOUT_SEASON]).fetchall())
        keep = np.array([i for i, g in enumerate(ids) if g in price])
        scores = {}
        for name, p in (("model", pred.p),
                        ("elo", np.array([elo[g] for g in ids])),
                        ("base_rate", np.full(len(ids), float(np.mean(y))))):
            s = score_set(p, y, seasons=seasons, game_ids=ids)
            scores[name] = s.__dict__.copy()
            print(f"  {name:<10} Brier {s.brier:.5f}  log loss "
                  f"{s.log_loss:.5f}  ECE {s.ece:.5f}")
        pm = np.array([price[ids[i]] for i in keep])
        s_mkt = score_set(pm, y[keep], seasons=[HOLDOUT_SEASON] * keep.size,
                          game_ids=[ids[i] for i in keep])
        s_mod = score_set(pred.p[keep], y[keep],
                          seasons=[HOLDOUT_SEASON] * keep.size,
                          game_ids=[ids[i] for i in keep])
        scores["market"] = s_mkt.__dict__.copy()
        print(f"  {'market':<10} Brier {s_mkt.brier:.5f}  log loss "
              f"{s_mkt.log_loss:.5f}  ECE {s_mkt.ece:.5f}  (n={keep.size:,})")
        print(f"  HEADLINE 1 deficit: {s_mod.brier - s_mkt.brier:+.5f} Brier "
              f"(pre-stated band 0.02-0.03)")
        panels.append({"label": sport.upper(), "p_model": pred.p[keep],
                       "p_market": pm, "y": y[keep]})

        tiers = risk_tiers(pred.p, y, reps=args.reps)
        print("  risk tiers:")
        for t in tiers:
            print(t.line())

        nested = {}
        x = np.column_stack([
            np.array([float(r["rating_diff_strength"]) for r in h_rows]),
            np.array([float(r["rest_diff"] or 0.0) for r in h_rows])])
        dates = np.array([r["game_date"] for r in h_rows], dtype=str)
        for horizon in PRICE_LOOKS:
            hp = dict(con.execute("""
                SELECT game_id, p FROM game_prices WHERE sport = ? AND
                  season = ? AND side = 'home' AND horizon = ?""",
                [sport, HOLDOUT_SEASON, horizon]).fetchall())
            dp = dict(con.execute("""
                SELECT game_id, p FROM game_prices WHERE sport = ? AND
                  season = ? AND side = 'home' AND horizon = ?""",
                [sport, DEV_SEASON, horizon]).fetchall())
            dk = [i for i, r in enumerate(d_rows) if r["game_id"] in dp]
            hk = [i for i, g in enumerate(ids) if g in hp]
            if len(hk) < 100 or len(dk) < 100:
                continue
            dx = np.column_stack([
                np.array([float(d_rows[i]["rating_diff_strength"]) for i in dk]),
                np.array([float(d_rows[i]["rest_diff"] or 0.0) for i in dk])])
            nf = fit_nested(np.array([dp[d_rows[i]["game_id"]] for i in dk]),
                            dx, np.array([d_rows[i]["y"] for i in dk]),
                            feature_names=("rating_diff_strength", "rest_diff"))
            got = apply_nested(nf, np.array([hp[ids[i]] for i in hk]),
                               x[np.array(hk)])
            for null in ("identity", "recalibrated"):
                cw = clark_west(y[np.array(hk)], got[null], got["b"],
                                dates=dates[np.array(hk)], reps=args.reps)
                print("  " + cw.lines(f"{horizon} B vs {null}")[0])
                nested.setdefault(horizon, {})[null] = cw.__dict__.copy()

        report["sports"][sport] = {"n": h_design.n, "scores": scores,
                                   "risk_tiers": [t.__dict__ for t in tiers],
                                   "nested": nested,
                                   "unseen_team_seasons":
                                       list(pred.unseen_team_seasons)}

    chart_reliability(panels, args.png, reps=args.reps)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    p = Path(args.out) / "holdout.json"
    p.write_text(json.dumps(report, indent=1, sort_keys=True, default=str)
                 + "\n", encoding="utf-8")
    print(f"\nwrote {p} and {args.png}")
    print("\nThe seal is spent. These numbers are final; re-running "
          "open_holdout refuses, and should.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
