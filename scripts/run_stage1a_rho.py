"""Stage 1a's proxy fitness gate (notes/profit-stage1-spec.md section 3).

    uv run python scripts/run_stage1a_rho.py

**The question.** Headline 2 split the market on TERMINAL volume, which does
not exist at bet time. Stage 1a proposes a bet-time proxy: the count of price
changes in the raw 1-minute series from market open to T-6h, where T is the
league's start time (Amendment 1). This script computes the proxy, its
Spearman rho against terminal volume on NBA 2024-25, and the misclassification
rate that rho implies.

**The gate is pre-committed: rho < 0.5 kills Signal L**, and the spec allows
no second proxy on this data. That is the whole point of writing it down
first, so this script reports the number and does not get a vote.

**Dev only, by construction.** Section 2 fits on NBA 2024-25 and evaluates on
2025-26, but 2025-26 is Chira's sealed holdout, so this script refuses to
touch it: the evaluation half belongs in Chira-gamble behind its firewall.
Nothing here reads a Chira model output either.

**Why the window function is filtered first.** Counting changes needs
`lag(p)` partitioned by game and ordered by `t`, and `price_points` is
145,626,599 rows. Ordering that whole table is the spill that broke week 3's
`ORDER BY` and week 7's ASOF join. The scan is cut to one sport-season, the
home side and `t <= tip - 6h` BEFORE the window, which leaves ~9M rows.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
import numpy as np

from chira.analysis import frame, open_frame
from chira.holdout import DEV_SEASON, HOLDOUT_SEASON
from chira.strata import assign_strata

# Section 3: the proxy is measured from market open to T-6h.
PROXY_HORIZON_SECONDS = 6 * 3600
RHO_GATE = 0.5
OUT = "data/stage1a"

_CUTOFF = ("CASE WHEN cutoff_source = 'league' THEN league_start_time "
           "ELSE game_start_time END")

_PROXY_SQL = f"""
WITH cut AS (
    SELECT sport, season, game_id,
           epoch(CAST({_CUTOFF} AS TIMESTAMPTZ))::BIGINT AS tip_t
    FROM priced WHERE sport = ? AND season = ?
),
pts AS (
    -- Filtered BEFORE the window: one sport-season, home side, pre-T-6h.
    SELECT pp.game_id, pp.t, pp.p
    FROM price_points pp
    JOIN cut c USING (sport, season, game_id)
    WHERE pp.sport = ? AND pp.season = ? AND pp.side = 'home'
      AND pp.t <= c.tip_t - {PROXY_HORIZON_SECONDS}
),
lagged AS (
    SELECT game_id, t, p,
           lag(p) OVER (PARTITION BY game_id ORDER BY t) AS prev_p
    FROM pts
)
SELECT l.game_id,
       count(*) AS n_points,
       count(*) FILTER (prev_p IS NOT NULL AND p <> prev_p) AS n_changes,
       min(t) AS first_t,
       any_value(c.tip_t) AS tip_t,
       (any_value(c.tip_t) - {PROXY_HORIZON_SECONDS} - min(t)) / 3600.0
           AS listed_hours
FROM lagged l
JOIN cut c ON c.game_id = l.game_id
GROUP BY l.game_id
ORDER BY l.game_id
"""


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Rank correlation, average ranks on ties (counts tie heavily)."""
    def rank(x):
        order = np.argsort(x, kind="mergesort")
        r = np.empty(len(x), dtype=float)
        r[order] = np.arange(1, len(x) + 1, dtype=float)
        # average ranks within tied groups
        xs = np.asarray(x)[order]
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[j + 1] == xs[i]:
                j += 1
            if j > i:
                r[order[i:j + 1]] = r[order[i:j + 1]].mean()
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    return float(np.corrcoef(ra, rb)[0, 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--sport", default="nba")
    ap.add_argument("--season", default=DEV_SEASON)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    if args.season == HOLDOUT_SEASON:
        print(f"refusing: {HOLDOUT_SEASON} is Chira's sealed holdout. The "
              f"Stage 1a evaluation half runs in Chira-gamble, behind its "
              f"firewall, not here.")
        return 2

    snaps = sorted(glob.glob("data/snapshots/census-*"))
    if not args.snapshot and not snaps:
        print("no snapshot found")
        return 2
    snap = args.snapshot or snaps[-1]
    con = open_frame(snap, verify=not args.no_verify)
    print(f"snapshot: {snap}")
    print(f"proxy: price changes from market open to T-{PROXY_HORIZON_SECONDS // 3600}h, "
          f"{args.sport} {args.season}")

    t0 = time.time()
    cur = con.execute(_PROXY_SQL, [args.sport, args.season,
                                   args.sport, args.season])
    cols = [d[0] for d in cur.description]
    proxy = {r[0]: dict(zip(cols, r, strict=True)) for r in cur.fetchall()}
    print(f"computed for {len(proxy):,} games in {time.time() - t0:.1f}s")

    f = frame(con, sport=args.sport, season=args.season)
    assign_strata(f)
    gid = np.asarray(f["game_id"], dtype=str)
    vol = np.asarray(f["volume"], dtype=float)
    vsrc = np.asarray(f["volume_source"], dtype=object)
    liq = np.asarray(f["liquidity"], dtype=object)

    have = np.array([g in proxy for g in gid])
    counts = np.array([proxy[g]["n_changes"] if g in proxy else -1
                       for g in gid], dtype=float)
    hours = np.array([proxy[g]["listed_hours"] if g in proxy else np.nan
                      for g in gid], dtype=float)

    # Amendment 4: games with no volume at all leave the rho test.
    usable = have & (vsrc != "absent") & np.isfinite(vol) & (counts >= 0)
    print(f"\ngames in the frame: {gid.size:,}")
    print(f"  with a proxy count: {have.sum():,}")
    print(f"  excluded, volume absent (Amendment 4): "
          f"{(have & (vsrc == 'absent')).sum():,}")
    print(f"  usable for rho: {usable.sum():,}")

    rho = spearman(counts[usable], vol[usable])
    cut = float(np.median(counts[usable]))
    print("\n=== THE GATE ===")
    print(f"  Spearman rho(change count, terminal volume) = {rho:.4f}")
    print(f"  gate: rho >= {RHO_GATE}")
    print(f"  VERDICT: {'PASS' if rho >= RHO_GATE else 'KILL'}")

    # misclassification against the strata headline 2 actually used
    proxy_low = counts <= cut
    vol_low = liq == "low"
    comp = usable & np.isin(liq, ["low", "high"])
    mis = float((proxy_low[comp] != vol_low[comp]).mean())
    print(f"\n  cut (NBA {args.season} median change count) = {cut:.0f}")
    print(f"  misclassification vs headline 2's volume strata: {mis:.1%} "
          f"of {comp.sum():,} games")
    print(f"  proxy says low on {proxy_low[comp].mean():.1%}, "
          f"volume says low on {vol_low[comp].mean():.1%}")

    print(f"\n  change count: median {np.median(counts[usable]):.0f}, "
          f"quartiles {np.quantile(counts[usable], [0.25, 0.75]).round(0)}, "
          f"range {counts[usable].min():.0f}-{counts[usable].max():.0f}")
    print(f"  listed hours to T-6h: median {np.nanmedian(hours[usable]):.1f}, "
          f"quartiles {np.nanquantile(hours[usable], [0.25, 0.75]).round(1)}")

    Path(args.out).mkdir(parents=True, exist_ok=True)
    doc = {"sport": args.sport, "season": args.season,
           "proxy_horizon_seconds": PROXY_HORIZON_SECONDS,
           "rho": rho, "rho_gate": RHO_GATE,
           "verdict": "pass" if rho >= RHO_GATE else "kill",
           "cut_change_count": cut,
           "misclassification_vs_volume_strata": mis,
           "n_frame": int(gid.size), "n_with_proxy": int(have.sum()),
           "n_usable_for_rho": int(usable.sum()),
           "n_volume_absent": int((have & (vsrc == "absent")).sum()),
           "listed_hours_median": float(np.nanmedian(hours[usable]))}
    p = Path(args.out) / f"rho-{args.sport}-{args.season}.json"
    p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                 encoding="utf-8")
    print(f"\nwrote {p}")
    if rho < RHO_GATE:
        print("\nSignal L is KILLED by kill criterion 1. The spec allows no "
              "second proxy on this data.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
