"""The week-2 census validation gate: run it on the first 200 games, not 5,084.

The eng review moved this gate earlier for a concrete reason. If it ran after
the full census, a label-agreement failure would mean re-pulling ~15,300
requests, and the schedule has no room for that. So: census 200 games, prove
the instrument, then spend the requests.

Four checks, and two of them test the TESTS rather than the data:

1. `label_agreement` -- the market's winner equals the league's winner on every
   priced game. This is the only defence against an orientation flip, which
   does not crash and instead mirrors the calibration curve about 0.5.
2. `complementarity` -- no game whose two outcome tokens failed to sum to 1.
3. `reconciliation` -- `scheduled == priced + misses`, with no orphan rows.
4. `fault_injection` -- delete a priced row and assert check 3 FAILS. An assert
   nobody has ever seen fail is an assert nobody knows is wired up.
5. `shuffled_join` -- re-pair each game's market winner with a DIFFERENT game's
   league winner and assert agreement collapses to chance. Without this, a
   100% agreement rate is equally consistent with a perfect join and with a
   degenerate one (every row labelled 'home', say).
"""

from __future__ import annotations

import math
import random

from .store import Store

# Shuffled agreement is NOT expected to be zero: re-pairing two binary labels
# that are both ~58% 'home' agrees by chance about half the time. The gate
# checks that the observed shuffled rate sits near that chance level instead of
# near 1.0, so the tolerance is in standard errors of the chance rate.
SHUFFLE_SE_TOLERANCE = 5.0

# The shuffle test loses all power when the label column is degenerate. If every
# game is labelled 'home', then true agreement, chance agreement, and shuffled
# agreement are all 1.0 and the check passes while proving nothing -- the same
# defect as an identity test that cannot detect the misalignment it claims to
# guard. Real leagues sit near 0.51-0.60, so a rate outside this band is
# evidence about the label column, not about home advantage.
PLAUSIBLE_HOME_WIN_RATE = (0.35, 0.75)

# Permutations, not a roll-by-one. A roll is a WEAK shuffle: if the label column
# is ordered (all home wins first, say) a one-step roll preserves nearly every
# pair and the "shuffled" agreement comes back at 0.98, failing the gate on
# correct data. Measured on a sorted 200-row fixture. A seeded permutation is
# insensitive to row order, and averaging several of them keeps the statistic
# from riding on one draw.
SHUFFLE_SEED = 20260912
SHUFFLE_DRAWS = 20


def check_label_agreement(store: Store, sport: str, season: str) -> dict:
    agreement = dict(store.db.execute(
        "SELECT label_agreement, count(*) FROM priced WHERE sport=? AND season=? "
        "GROUP BY label_agreement", [sport, season]).fetchall())
    disagreements = store.db.execute(
        "SELECT count(*) FROM misses WHERE sport=? AND season=? "
        "AND reason='label_disagreement'", [sport, season]).fetchone()[0]
    n = sum(agreement.values())
    return {
        "name": "label_agreement",
        "passed": disagreements == 0 and agreement.get("agree", 0) == n and n > 0,
        "n_priced": n,
        "by_value": agreement,
        "disagreements_in_misses": disagreements,
    }


def check_complementarity(store: Store, sport: str, season: str) -> dict:
    failed = store.db.execute(
        "SELECT count(*) FROM misses WHERE sport=? AND season=? "
        "AND reason='complementarity_failed'", [sport, season]).fetchone()[0]
    unchecked = store.db.execute(
        "SELECT count(*) FROM priced WHERE sport=? AND season=? "
        "AND complement_ok IS NULL", [sport, season]).fetchone()[0]
    checked = store.db.execute(
        "SELECT count(*) FROM priced WHERE sport=? AND season=? "
        "AND complement_ok = TRUE", [sport, season]).fetchone()[0]
    return {
        "name": "complementarity",
        "passed": failed == 0 and checked > 0,
        "checked_ok": checked,
        # Not a failure: the away token's series was absent, so the check could
        # not run. Counted so it can never masquerade as a passing check.
        "unchecked_no_away_series": unchecked,
        "failed": failed,
    }


def check_reconciliation(store: Store, sport: str, season: str, *,
                         require_complete: bool = True) -> dict:
    """`require_complete=False` when the gate runs on a slice, not a full pass."""
    extra = {"double_counted": store.double_counted(), "orphans": store.orphans()}
    try:
        r = store.assert_reconciled(sport, season, require_complete=require_complete)
        if not require_complete:
            # Do not report `balanced` on a slice. It is False by construction
            # (1,030 of 1,230 games are simply not attempted yet) and printing
            # "[ok] reconciliation: balanced=False" reads as a passing failure.
            r = {k: v for k, v in r.items() if k != "balanced"}
            r["partial_pass"] = True
        return {"name": "reconciliation", "passed": True, **r, **extra}
    except AssertionError as e:
        return {"name": "reconciliation", "passed": False, "error": str(e),
                **store.reconcile(sport, season), **extra}


def check_fault_injection(store: Store, sport: str, season: str) -> dict:
    """Delete one priced row inside a transaction; the assert must fire. Then roll back."""
    before = store.digest()
    victim = store.db.execute(
        "SELECT game_id FROM priced WHERE sport=? AND season=? ORDER BY game_id LIMIT 1",
        [sport, season]).fetchone()
    if victim is None:
        return {"name": "fault_injection", "passed": False,
                "error": "no priced rows to injure"}
    store.db.execute("BEGIN")
    fired = False
    try:
        store.db.execute("DELETE FROM priced WHERE sport=? AND season=? AND game_id=?",
                         [sport, season, victim[0]])
        try:
            # Injected as a DOUBLE-COUNT rather than a deletion, so the check
            # fires on a slice too: deleting a row only breaks the full-pass
            # balance, while a game in both tables is always illegal.
            store.db.execute(
                "INSERT OR REPLACE INTO misses (sport, season, game_id, reason, attempted) "
                "VALUES (?,?,?,?,?)", [sport, season, victim[0], "no_market", "[]"])
            store.db.execute(
                "INSERT OR REPLACE INTO priced (sport, season, game_id, slug, convention, "
                "p_home_close, n_pre_tipoff, secs_before_tip, label_agreement) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                [sport, season, victim[0], "injected", "et", 0.5, 1, 1, "agree"])
            store.assert_reconciled(sport, season, require_complete=False)
        except AssertionError:
            fired = True
    finally:
        store.db.execute("ROLLBACK")
    after = store.digest()
    return {
        "name": "fault_injection",
        "passed": fired and after == before,
        "assert_fired": fired,
        "store_restored": after == before,
        "victim": victim[0],
    }


def check_shuffled_join(store: Store, sport: str, season: str) -> dict:
    """Roll the market winners by one game and assert agreement collapses."""
    rows = store.db.execute(
        "SELECT p.market_winner, g.winner FROM priced p JOIN games g "
        "USING (sport, season, game_id) WHERE p.sport=? AND p.season=? "
        "ORDER BY p.game_id", [sport, season]).fetchall()
    n = len(rows)
    if n < 30:
        return {"name": "shuffled_join", "passed": False,
                "error": f"only {n} priced rows; need >= 30 for a meaningful shuffle"}
    market = [r[0] for r in rows]
    league = [r[1] for r in rows]
    true_rate = sum(m == lg for m, lg in zip(market, league, strict=True)) / n

    rng = random.Random(SHUFFLE_SEED)
    draws = []
    for _ in range(SHUFFLE_DRAWS):
        permuted = rng.sample(market, n)
        draws.append(sum(m == lg for m, lg in zip(permuted, league, strict=True)) / n)
    shuffled_rate = sum(draws) / len(draws)

    p_home = sum(lg == "home" for lg in league) / n
    lo, hi = PLAUSIBLE_HOME_WIN_RATE
    if not lo <= p_home <= hi:
        return {"name": "shuffled_join", "passed": False,
                "error": (f"home win rate {p_home:.3f} is outside {PLAUSIBLE_HOME_WIN_RATE}; "
                          f"the label column looks degenerate and the shuffle test "
                          f"would have no power"),
                "home_win_rate": round(p_home, 4), "n": n}
    chance = p_home ** 2 + (1 - p_home) ** 2
    se = math.sqrt(max(chance * (1 - chance), 1e-9) / n)
    within = abs(shuffled_rate - chance) <= SHUFFLE_SE_TOLERANCE * se
    return {
        "name": "shuffled_join",
        "passed": true_rate == 1.0 and within,
        "true_rate": round(true_rate, 4),
        "shuffled_rate": round(shuffled_rate, 4),
        "shuffled_max": round(max(draws), 4),
        "shuffled_draws": len(draws),
        "chance_rate": round(chance, 4),
        "chance_se": round(se, 4),
        "shuffled_within_tolerance": within,
        "home_win_rate": round(p_home, 4),
    }


def coverage(store: Store, sport: str, season: str) -> dict:
    r = store.reconcile(sport, season)
    conventions = dict(store.db.execute(
        "SELECT convention, count(*) FROM priced WHERE sport=? AND season=? "
        "GROUP BY convention", [sport, season]).fetchall())
    attempted = r["priced"] + r["misses"]
    return {
        **r,
        "attempted": attempted,
        "coverage_of_attempted": round(r["priced"] / attempted, 4) if attempted else None,
        "conventions": conventions,
        "miss_reasons": store.miss_reasons(sport, season),
    }


def run_gate(store: Store, sport: str, season: str, *,
             require_complete: bool = True) -> dict:
    checks = [
        check_label_agreement(store, sport, season),
        check_complementarity(store, sport, season),
        check_reconciliation(store, sport, season, require_complete=require_complete),
        check_fault_injection(store, sport, season),
        check_shuffled_join(store, sport, season),
    ]
    return {
        "sport": sport,
        "season": season,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "coverage": coverage(store, sport, season),
    }


def format_report(result: dict) -> str:
    lines = [f"CENSUS GATE {result['sport']} {result['season']}: "
             f"{'PASS' if result['passed'] else 'FAIL'}"]
    for c in result["checks"]:
        mark = "ok  " if c["passed"] else "FAIL"
        detail = ", ".join(f"{k}={v}" for k, v in c.items()
                           if k not in ("name", "passed"))
        lines.append(f"  [{mark}] {c['name']}: {detail}")
    cov = result["coverage"]
    lines.append(f"  coverage: {cov['priced']}/{cov['attempted']} attempted "
                 f"({cov['coverage_of_attempted']}), scheduled={cov['scheduled']}, "
                 f"pending={cov['pending']}")
    lines.append(f"  conventions: {cov['conventions']}")
    lines.append(f"  miss reasons: {cov['miss_reasons']}")
    return "\n".join(lines)
