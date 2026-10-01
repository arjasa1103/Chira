"""The deterministic pre-game team rating (PREREGISTRATION Amendment 5b).

Elo, updated after every game, computed OUTSIDE the model and entered into it
as the pre-game rating difference. Section 5's A4 pre-commit chose a
deterministic rating over a latent state-space walk for a cost reason: a walk
is ~75k latent variables on 5,084 observations, and this is a few hundred
lines that fit in the available weeks.

Everything here is pure. The 2023-24 burn-in results come from
`scripts/fetch_burnin.py` and the later seasons from the snapshot; this module
takes game dicts and returns ratings.

**The availability rule is the same one the feature store uses.** A game's
pre-game rating may only reflect games whose result was PUBLIC when it
started, so updates are queued and applied at `start + RESULT_DELAY_SECONDS`,
not at the moment the earlier game tipped off. In a backtest this rarely
binds -- a team's own previous game is a day earlier -- but Elo is a
LEAGUE-wide quantity, so an opponent's game three hours earlier the same
evening binds constantly. Measured on the real schedule, it moves thousands of
updates (notes/week8-ratings.md).

**Two readings of Amendment 5b are recorded where the text is ambiguous**, and
both are flagged in the note rather than silently chosen:

1. *"the winner's pre-game rating edge"* in the margin multiplier is taken to
   INCLUDE the home bonus, matching the published FiveThirtyEight form the
   amendment cites, so it is the same quantity that entered the expectation.
   `WINNER_EDGE_INCLUDES_H` records the choice. **Measured, it does not
   matter**: both readings select the same grid point for both sports, with
   log-loss gaps of 7e-6 (NBA) and 2.2e-5 (NHL).
2. The season carry-over is applied at **every** season change, including the
   one into the burn-in's following season, which is what "applied identically
   at every change" requires.
3. **The model takes `rating_diff_strength`, which EXCLUDES the home bonus**,
   not `rating_diff`, which includes it. `MODEL_COVARIATE` names the field so
   the choice is enforced rather than remembered. See that constant.

Nothing here reads a price, and nothing here reads 2025-26. The grid is tuned
on 2024-25 only; `scripts/run_ratings.py` calls `holdout.assert_dev_only` on
the criterion set.
"""

from __future__ import annotations

import math
from heapq import heappop, heappush

from .features import RESULT_DELAY_SECONDS
from .venues import is_neutral_site

ELO_START = 1500.0

# The margin multiplier, published FiveThirtyEight NBA form, used for both
# sports and never tuned (Amendment 5b).
MOV_OFFSET = 3.0
MOV_EXPONENT = 0.8
MOV_DENOM_BASE = 7.5
MOV_DENOM_SLOPE = 0.006

# See the module docstring, reading 1.
WINNER_EDGE_INCLUDES_H = True

# The tuning grid, verbatim from Amendment 5b. 140 NBA points, 105 NHL.
GRID: dict[str, dict[str, tuple]] = {
    "nba": {"k": (10, 15, 20, 25, 30),
            "h": (50, 75, 100, 125),
            "c": (0.0, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9)},
    "nhl": {"k": (8, 12, 16, 20, 30),
            "h": (25, 50, 75),
            "c": (0.0, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9)},
}
GRID_SIZE = {s: len(g["k"]) * len(g["h"]) * len(g["c"]) for s, g in GRID.items()}
assert GRID_SIZE == {"nba": 140, "nhl": 105}, GRID_SIZE

# The burn-in season. Rating input only: never a model row, never scored, and
# no 2023-24 price is read anywhere in this project (section 1).
BURNIN_SEASON = "2023-24"

# Clamp for the log loss, so one impossible game cannot decide the grid. Elo
# probabilities never reach 0 or 1 in practice -- a 1000-point edge is 0.9968
# -- so this is a guard, not a thumb on the scale.
LOG_LOSS_EPS = 1e-15


# --- FROZEN, 2026-10-01 ----------------------------------------------------
#
# Chosen by `scripts/run_ratings.py`: lowest log loss of the Elo home-win
# probability over every 2024-25 game, with 2023-24 as burn-in and NOT in the
# criterion. Ties to the smaller K, then the smaller H, then the larger c.
# Every grid point and its log loss is in notes/week8-ratings.md.
#
# Committed before any 2025-26 rating was computed. Git history is the proof
# of order, which is the whole mechanism Amendment 5b relies on.
#
# **Both optima sit on a grid edge, reported as a limitation and NOT widened**
# (Amendment 5b forbids widening after seeing the result):
#   - NBA H=50 is the grid's MINIMUM. A 50-point bonus implies a 0.5717 home
#     win rate at equal ratings against an observed 0.5439, so the grid floor
#     is above where the data wants to be.
#   - NHL c=0.9 is the grid's MAXIMUM: it wants to carry more rating across
#     the season boundary than the grid allows.
CHOSEN: dict[str, dict[str, float]] = {
    "nba": {"k": 20, "h": 50, "c": 0.6},
    "nhl": {"k": 16, "h": 50, "c": 0.9},
}

# The criterion values those points produced, pinned so a refactor that
# changes the arithmetic fails loudly rather than quietly re-rating.
CHOSEN_LOG_LOSS = {"nba": 0.60781, "nhl": 0.66618}
CHOSEN_BRIER = {"nba": 0.21044, "nhl": 0.23686}


# The field the model may use as its rating covariate (Amendment 5b, third
# reading, decided 2026-10-01).
#
# `rating_diff` is `r_home + H - r_away`: the quantity that produced
# `p_home_elo`, which the grid was tuned on and which must not change.
# **It is the wrong input for the model**, because PLAN Phase 4 pools a
# per-team home-advantage term of its own. Feeding a covariate that already
# carries H puts home advantage in twice: once fixed at a magnitude chosen by
# Elo log loss on 1,230 NBA games, once as a pooled parameter.
#
# Worse, the two are barely separable. `H * 1[not neutral]` is constant across
# **2,531 of 2,542 dev games** -- there are only 11 neutral-site games in
# 2024-25 across both sports -- so the H component is collinear with the
# model's own home term except on 0.43% of the sample. That is a near-singular
# design, not a modelling choice.
#
# So the model takes the pure strength difference and owns home advantage
# entirely: the global intercept plus the pooled per-team term, switched off
# for a neutral-site game exactly as Elo sets H = 0. **The neutral adjustment
# is therefore weakly identified** -- 11 dev games -- and must be reported as
# shrunk toward its prior, never as an estimate.
MODEL_COVARIATE = "rating_diff_strength"


def expected_home(r_home: float, r_away: float, h: float) -> float:
    """P(home wins) on the standard Elo scale. `h` is 0 at a neutral site."""
    return 1.0 / (1.0 + 10.0 ** (-(r_home + h - r_away) / 400.0))


def margin_multiplier(mov: int | float, winner_edge: float) -> float:
    """(MOV + 3)^0.8 / (7.5 + 0.006 * the winner's pre-game rating edge).

    `mov` is the winner's margin and must be positive: a tie has no winner and
    neither league leaves one on the board (an NHL shootout win is 1 goal).
    The denominator is the autocorrelation correction -- a favourite winning
    big moves less than an underdog winning big.
    """
    if mov <= 0:
        raise ValueError(f"margin must be positive, got {mov}; a tied game has "
                         f"no winner and neither league produces one")
    return ((mov + MOV_OFFSET) ** MOV_EXPONENT
            / (MOV_DENOM_BASE + MOV_DENOM_SLOPE * winner_edge))


def carry_over(rating: float, c: float) -> float:
    """r_new = 1500 + c * (r_old - 1500). c = 0 is a fresh start."""
    return ELO_START + c * (rating - ELO_START)


def _delay_for(sport: str, delays: dict[str, int] | None = None) -> int:
    """An unknown sport gets the LONGEST configured delay, never zero, the
    same rule `features._delay_case` uses and for the same reason."""
    delays = delays or RESULT_DELAY_SECONDS
    return delays.get(sport, max(delays.values()))


def is_neutral(g: dict) -> bool:
    """The league's flag OR the vendored NBA neutral-site table.

    **Applied here, inside the walk, so no caller can forget it.** It used to
    live in `scripts/run_ratings.py`, and the burn-in parquet stores the NBA's
    own flag, which is False for all 1,230 2023-24 games (`schedule.nba_games`
    carries no neutral-site field at all). A rating walk built anywhere else --
    week 9's 2025-26 walk is the next one -- would have scored a Paris game
    with a home bonus, and that wrong update persists for the rest of the
    season. The same OR `features.py` applies in SQL.
    """
    return bool(g.get("neutral_site")) or is_neutral_site(
        g["sport"], g["season"], str(g["game_id"]))


def run_ratings(games: list[dict], *, k: float, h: float, c: float,
                start: float = ELO_START,
                result_delay: dict[str, int] | None = None,
                _with_final: bool = False):
    """Walk the games in start-time order and return one row per game.

    `games` need `sport`, `season`, `game_id`, `away`, `home`, `away_pts`,
    `home_pts`, `winner`, `neutral_site` and `start_t` (unix seconds). They
    are sorted here, so the caller's order does not matter.

    Each row carries the PRE-game ratings and the home expectation. The
    expectation is the quantity the grid is scored on and the rating
    difference is what enters the model. For the settled end-of-run ratings
    use `final_ratings`, which cannot be reconstructed from the rows.
    """
    delays = dict(RESULT_DELAY_SECONDS)
    delays.update(result_delay or {})
    ordered = sorted(games, key=lambda g: (g["start_t"], g["sport"],
                                           str(g["game_id"])))
    rating: dict[str, float] = {}
    season_of: dict[str, str] = {}
    # (available_at, seq, team, delta). `seq` keeps the heap total-ordered
    # without ever comparing the dicts behind it.
    pending: list[tuple[int, int, str, float]] = []
    seq = 0
    out: list[dict] = []

    def apply_due(now: int) -> None:
        while pending and pending[0][0] <= now:
            _, _, team, delta = heappop(pending)
            rating[team] = rating.get(team, start) + delta

    for g in ordered:
        sport, season = g["sport"], g["season"]
        away = f"{sport}:{g['away']}"
        home = f"{sport}:{g['home']}"
        apply_due(g["start_t"])

        for team in (away, home):
            if team not in rating:
                rating[team] = start
                season_of[team] = season
            elif season_of[team] != season:
                # Every season change, applied identically (Amendment 5b).
                # Pending updates from the previous season are flushed first
                # by apply_due above; a result that only became public after
                # the new season began would be carried over twice otherwise.
                rating[team] = carry_over(rating[team], c)
                season_of[team] = season

        neutral = is_neutral(g)
        hb = 0.0 if neutral else float(h)
        r_home, r_away = rating[home], rating[away]
        p_home = expected_home(r_home, r_away, hb)
        y = 1.0 if g["winner"] == "home" else 0.0

        mov = abs(int(g["home_pts"]) - int(g["away_pts"]))
        if WINNER_EDGE_INCLUDES_H:
            edge = (r_home + hb - r_away) if y else (r_away - r_home - hb)
        else:
            edge = (r_home - r_away) if y else (r_away - r_home)
        delta = float(k) * margin_multiplier(mov, edge) * (y - p_home)

        # The merged table, not the module constant: `result_delay` used to be
        # accepted and silently ignored, so a delay sensitivity run would
        # have reported the default walk under another name.
        available_at = g["start_t"] + _delay_for(sport, delays)
        heappush(pending, (available_at, seq, home, delta))
        heappush(pending, (available_at, seq + 1, away, -delta))
        seq += 2

        out.append({
            "sport": sport, "season": season, "game_id": str(g["game_id"]),
            "et_date": g.get("et_date"), "away": g["away"], "home": g["home"],
            "start_t": g["start_t"],
            "r_home_pre": r_home, "r_away_pre": r_away,
            "home_bonus": hb,
            # With H: what produced p_home_elo. The grid was tuned on this.
            "rating_diff": r_home + hb - r_away,
            # Without H: the model's covariate. See MODEL_COVARIATE.
            "rating_diff_strength": r_home - r_away,
            "p_home_elo": p_home, "y": y,
            "mov": mov, "delta": delta,
            "neutral_site": neutral,
        })

    apply_due(2 ** 62)   # settle everything, so final ratings are complete
    return (out, dict(rating)) if _with_final else out


def final_ratings(games: list[dict], **kwargs) -> dict[str, float]:
    """Every team's rating once all updates have settled.

    **It re-walks rather than reading the rows, because the rows cannot
    answer this.** A row carries the PRE-game rating, and under the
    availability delay a team's last game can start before an earlier result
    of its own is public -- so `r_pre + delta` from the last row silently
    drops the pending update. Caught by the zero-sum test: two games, three
    teams, 4481.98 against an invariant 4500.
    """
    _, final = run_ratings(games, _with_final=True, **kwargs)
    return final


def log_loss(rows: list[dict]) -> float:
    """Mean negative log likelihood of the Elo home-win probability."""
    if not rows:
        raise ValueError("log loss of an empty set is undefined")
    total = 0.0
    for r in rows:
        p = min(max(r["p_home_elo"], LOG_LOSS_EPS), 1.0 - LOG_LOSS_EPS)
        total += -(r["y"] * math.log(p) + (1.0 - r["y"]) * math.log(1.0 - p))
    return total / len(rows)


def brier(rows: list[dict]) -> float:
    if not rows:
        raise ValueError("Brier of an empty set is undefined")
    return sum((r["p_home_elo"] - r["y"]) ** 2 for r in rows) / len(rows)


def grid_search(games: list[dict], sport: str, *, criterion_season: str,
                result_delay: dict[str, int] | None = None) -> list[dict]:
    """Every grid point with its criterion log loss, best first.

    The criterion is the log loss over `criterion_season` ONLY; the burn-in
    season is rating input and is never scored (Amendment 5b). Ties go to the
    smaller K, then the smaller H, then the LARGER c, which is why the sort
    key negates c.
    """
    grid = GRID[sport]
    scored: list[dict] = []
    for k in grid["k"]:
        for h in grid["h"]:
            for c in grid["c"]:
                rows = run_ratings(games, k=k, h=h, c=c,
                                   result_delay=result_delay)
                crit = [r for r in rows if r["season"] == criterion_season]
                if not crit:
                    raise ValueError(
                        f"no {criterion_season} games for {sport}: the grid "
                        f"would be scored on nothing")
                scored.append({"sport": sport, "k": k, "h": h, "c": c,
                               "log_loss": log_loss(crit),
                               "brier": brier(crit), "n": len(crit)})
    scored.sort(key=lambda r: (r["log_loss"], r["k"], r["h"], -r["c"]))
    return scored


def on_grid_edge(point: dict, sport: str) -> list[str]:
    """Which of K, H, c sit on the edge of the grid.

    Amendment 5b: an optimum on the edge is reported as a limitation, and the
    grid is never widened after seeing it. Returning the names makes that
    report automatic rather than a thing someone remembers to look for.
    """
    grid = GRID[sport]
    return [name for name in ("k", "h", "c")
            if point[name] in (min(grid[name]), max(grid[name]))]
