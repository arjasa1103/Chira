"""The week-2 census validation gate: run it on a 200-game stride slice, not all 5,084.

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
5. `price_discriminates` -- p_home_close must be higher when the home team won
   than when it lost. This is the link label agreement does NOT test:
   `market_winner` comes from `outcomePrices[1]` while `p_home_close` comes from
   the series of `clobTokenIds[1]`, so a flipped token leg leaves every row
   agreeing, complementarity passing, and p_home_close silently carrying the
   AWAY probability.
6. `shuffled_join` -- re-pair each game's market winner with a DIFFERENT game's
   league winner and report how far agreement falls.

**A known limit of check 6, recorded so nobody over-reads it.** `census_game`
routes every label disagreement to `misses`, so `priced.market_winner` equals
`games.winner` elementwise BY CONSTRUCTION and `true_rate` is 1.0 whatever the
join does. The permuted rate then concentrates at the chance rate as a matter of
arithmetic. The check is a useful measurement of the chance level and a guard on
the join key, but it is NOT independent evidence that the join is correct. The
real E1 evidence is `count(misses where reason='label_disagreement') == 0`,
which check 1 queries, plus check 5 for the token leg.
"""

from __future__ import annotations

import math
import random
import statistics

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

# `checked > 0` was not a gate. A population with complementarity verified on ONE
# row of 200 and the away series absent on the other 199 passed, because nothing
# compared the two counts. Measured on 960 real priced games: 0 unchecked, so a
# 5% allowance is far outside anything observed and still fails the pathological
# case the old condition waved through.
MAX_UNCHECKED_FRACTION = 0.05

# Permutations, not a roll-by-one. A roll is a WEAK shuffle: if the label column
# is ordered (all home wins first, say) a one-step roll preserves nearly every
# pair and the "shuffled" agreement comes back at 0.98, failing the gate on
# correct data. Measured on a sorted 200-row fixture. A seeded permutation is
# insensitive to row order, and averaging several of them keeps the statistic
# from riding on one draw.
SHUFFLE_SEED = 20260912
SHUFFLE_DRAWS = 20

# The token-leg check. DERIVED FROM MEASUREMENT, rounded OUTWARD -- an eyeballed
# 3.0 failed both NHL seasons on correct data, which is the same false-fire
# defect as setting a calibration gate inside its own null.
#
# Measured on the four clean week-2 slices:
#
#   sport season     n     gap    sigma
#   nba   2024-25   200   0.161    5.88
#   nba   2025-26   199   0.208    7.60
#   nhl   2024-25   136   0.057    2.73
#   nhl   2025-26   200   0.042    2.95
#
# A flipped clobTokenIds leg inverts the sign, so even NHL's weak signal is
# caught decisively by `gap > 0` alone; the sigma floor is there to also catch a
# degenerate or constant price column, which sits at sigma ~ 0. 2.0 is below the
# 2.73 minimum observed and still two sigma clear of degenerate.
#
# Worth noting independently: NHL's discrimination is ~3x weaker than NBA's.
# That is a real property of the sport, and it bears on which sport is primary.
MIN_DISCRIMINATION_SIGMA = 2.0


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
    total = checked + unchecked
    unchecked_fraction = (unchecked / total) if total else 1.0
    return {
        "name": "complementarity",
        "passed": (failed == 0 and checked > 0
                   and unchecked_fraction <= MAX_UNCHECKED_FRACTION),
        "checked_ok": checked,
        "unchecked_fraction": round(unchecked_fraction, 4),
        # Not a failure: the away token's series was absent, so the check could
        # not run. Counted so it can never masquerade as a passing check.
        "unchecked_no_away_series": unchecked,
        "failed": failed,
    }


def check_reconciliation(store: Store, sport: str, season: str, *,
                         require_complete: bool = True) -> dict:
    """`require_complete=False` when the gate runs on a slice, not a full pass.

    On a slice this also checks the identity that DOES hold instant by instant:
    every game the run touched is in exactly one table. Without it, a game
    settled in NEITHER table -- the failure the store exists to make impossible
    -- passed the slice gate, because `pending > 0` is expected on a slice and
    a lost game just makes it one larger.
    """
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


def check_price_series(store: Store, sport: str, season: str) -> dict:
    """Every priced game carries its raw series, and no series is orphaned.

    The snapshot ships the raw series as its public artifact (PLAN.md F10). A
    priced game with no stored series would ship an empty one with nothing
    anywhere saying so.
    """
    summary = store.points_summary(sport, season)
    return {
        "name": "price_series",
        "passed": (summary["priced_missing_series"] == 0
                   and summary["orphan_series"] == 0),
        **summary,
    }


def check_fault_injection(store: Store, sport: str, season: str) -> dict:
    """Corrupt the store two ways inside a transaction; both asserts must fire.

    Two injections, because they fail different guards and the second one was
    the guard that mattered:

      1. a DOUBLE COUNT (the game in both tables), caught by double_counted()
      2. a LOST GAME (the game in neither table), which on a slice is caught
         only by the attempted-set check -- `pending > 0` is expected on a
         slice, so a deleted row used to pass every gate silently

    Rolled back either way; the digest is compared before and after.
    """
    before = store.digest()
    victim = store.db.execute(
        "SELECT game_id FROM priced WHERE sport=? AND season=? ORDER BY game_id LIMIT 1",
        [sport, season]).fetchone()
    if victim is None:
        return {"name": "fault_injection", "passed": False,
                "error": "no priced rows to injure"}
    attempted = store.attempted_game_ids(sport, season)
    double_fired = lost_fired = False

    store.db.execute("BEGIN")
    try:
        store.db.execute(
            "INSERT OR REPLACE INTO misses (sport, season, game_id, reason, attempted) "
            "VALUES (?,?,?,?,?)", [sport, season, victim[0], "no_market", "[]"])
        try:
            store.assert_reconciled(sport, season, require_complete=False)
        except AssertionError:
            double_fired = True
    finally:
        store.db.execute("ROLLBACK")

    store.db.execute("BEGIN")
    try:
        store.db.execute("DELETE FROM priced WHERE sport=? AND season=? AND game_id=?",
                         [sport, season, victim[0]])
        try:
            store.assert_attempted_settled(sport, season, attempted)
        except AssertionError:
            lost_fired = True
    finally:
        store.db.execute("ROLLBACK")

    after = store.digest()
    return {
        "name": "fault_injection",
        "passed": double_fired and lost_fired and after == before,
        "double_count_caught": double_fired,
        "lost_game_caught": lost_fired,
        "store_restored": after == before,
        "victim": victim[0],
    }


def check_price_discriminates(store: Store, sport: str, season: str) -> dict:
    """Does p_home_close actually predict the home team winning?

    This is the link label agreement does NOT test. `market_winner` is derived
    from `outcomePrices[1]`, while `p_home_close` is derived from the price
    series of `clobTokenIds[1]`. Label agreement therefore proves outcomes and
    outcomePrices are index-aligned to home, and says nothing about whether
    clobTokenIds is aligned with them. If that leg ever flips, every row still
    agrees, complementarity still passes (p_away + p_home = 1 either way), and
    p_home_close is silently the AWAY probability -- the mirrored-curve failure
    extract.py's docstring names as the thing it defends against.

    Measured on the week-2 slices: mean p_home_close is 0.66 when the home team
    won and 0.43 when it lost (NBA 2024-25), so the signal is large and the
    check is cheap. A flipped token leg inverts the sign.
    """
    rows = store.db.execute(
        "SELECT p.p_home_close, g.winner FROM priced p JOIN games g "
        "USING (sport, season, game_id) WHERE p.sport=? AND p.season=?",
        [sport, season]).fetchall()
    n = len(rows)
    if n < 30:
        return {"name": "price_discriminates", "passed": False,
                "error": f"only {n} priced rows; need >= 30"}
    home = [p for p, w in rows if w == "home"]
    away = [p for p, w in rows if w == "away"]
    if not home or not away:
        return {"name": "price_discriminates", "passed": False,
                "error": "one outcome class is empty; cannot measure discrimination"}
    gap = (sum(home) / len(home)) - (sum(away) / len(away))
    # Standard error of the difference in means, pooled crudely.
    var = (statistics.pvariance(home) / len(home)
           + statistics.pvariance(away) / len(away))
    se = math.sqrt(var) if var > 0 else 1e-9
    return {
        "name": "price_discriminates",
        "passed": gap > 0 and gap / se >= MIN_DISCRIMINATION_SIGMA,
        "mean_when_home_won": round(sum(home) / len(home), 4),
        "mean_when_away_won": round(sum(away) / len(away), 4),
        "gap": round(gap, 4),
        "sigma": round(gap / se, 2),
        "n": n,
    }


def check_shuffled_join(store: Store, sport: str, season: str) -> dict:
    """Re-pair market winners with other games' league winners over SHUFFLE_DRAWS
    seeded permutations; agreement must collapse to the chance rate.

    A permutation, NOT a roll: see SHUFFLE_SEED for the measurement that killed the
    roll. See also the known limits recorded in the module docstring.
    """
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


def attempted_by_month(store: Store, sport: str, season: str) -> dict:
    """Attempted / scheduled per month.

    A slice that is 57% March-April against a schedule that is 28% is not a
    sample you can quote a coverage or liquidity number from, and nothing
    recorded that until two of the four week-2 slices had already been quoted.
    """
    rows = store.db.execute(
        "SELECT strftime(g.et_date, '%Y-%m') AS m, count(*), "
        "  sum(CASE WHEN g.game_id IN ("
        "    SELECT game_id FROM priced WHERE sport=? AND season=? "
        "    UNION SELECT game_id FROM misses WHERE sport=? AND season=?) "
        "  THEN 1 ELSE 0 END) "
        "FROM games g WHERE g.sport=? AND g.season=? GROUP BY m ORDER BY m",
        [sport, season, sport, season, sport, season]).fetchall()
    return {m: {"scheduled": sched, "attempted": att} for m, sched, att in rows}


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
        "attempted_by_month": attempted_by_month(store, sport, season),
        # Amendment 1 made visible: which cutoff each game used, which market
        # type was priced, and how often Gamma's own tipoff was badly off.
        "cutoff_sources": dict(store.db.execute(
            "SELECT coalesce(cutoff_source, 'unrecorded'), count(*) FROM priced "
            "WHERE sport=? AND season=? GROUP BY ALL", [sport, season]).fetchall()),
        "market_types": dict(store.db.execute(
            "SELECT coalesce(market_type, 'untyped'), count(*) FROM priced "
            "WHERE sport=? AND season=? GROUP BY ALL", [sport, season]).fetchall()),
        "gamma_tipoff_off_over_1h": store.db.execute(
            "SELECT count(*) FROM priced WHERE sport=? AND season=? "
            "AND abs(gamma_delta_min) > 60", [sport, season]).fetchone()[0],
    }


def run_gate(store: Store, sport: str, season: str, *,
             require_complete: bool = True) -> dict:
    checks = [
        check_label_agreement(store, sport, season),
        check_complementarity(store, sport, season),
        check_reconciliation(store, sport, season, require_complete=require_complete),
        check_price_series(store, sport, season),
        check_fault_injection(store, sport, season),
        check_price_discriminates(store, sport, season),
        check_shuffled_join(store, sport, season),
    ]
    return {
        "sport": sport,
        "season": season,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "coverage": coverage(store, sport, season),
        # Ties the verdict to the exact store state and the runs that built it.
        "store_digest": store.digest(),
        "schema_version": store.schema_version,
        "runs": [r[0] for r in store.db.execute(
            "SELECT run_id FROM runs ORDER BY started_at").fetchall()],
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
    lines.append(f"  cutoff sources: {cov['cutoff_sources']}  market types: "
                 f"{cov['market_types']}  gamma tipoff off >1h: "
                 f"{cov['gamma_tipoff_off_over_1h']}")
    lines.append(f"  miss reasons: {cov['miss_reasons']}")
    return "\n".join(lines)
