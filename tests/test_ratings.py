"""The Elo rating (PREREGISTRATION Amendment 5b).

Pure and offline: the module takes game dicts and returns ratings, so these
build the schedules they need rather than reading the snapshot or the
burn-in parquet, neither of which is in git.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from chira.features import RESULT_DELAY_SECONDS
from chira.ratings import (
    CHOSEN,
    CHOSEN_BRIER,
    CHOSEN_LOG_LOSS,
    ELO_START,
    GRID,
    GRID_SIZE,
    brier,
    carry_over,
    expected_home,
    final_ratings,
    grid_search,
    log_loss,
    margin_multiplier,
    on_grid_edge,
    run_ratings,
)

DAY = 86400
T0 = 1_700_000_000


def g(gid, start, away, home, ap, hp, *, sport="nba", season="2024-25",
      neutral=False):
    return {"sport": sport, "season": season, "game_id": str(gid),
            "et_date": "2025-01-01", "away": away, "home": home,
            "away_pts": ap, "home_pts": hp,
            "winner": "home" if hp > ap else "away",
            "neutral_site": neutral, "start_t": start}


class TestTheEloScale:
    def test_equal_ratings_with_no_bonus_is_a_coinflip(self):
        assert expected_home(1500, 1500, 0) == 0.5

    def test_four_hundred_points_is_ten_to_one(self):
        assert expected_home(1900, 1500, 0) == pytest.approx(10 / 11, abs=1e-9)

    def test_the_home_bonus_moves_the_expectation(self):
        assert expected_home(1500, 1500, 100) == pytest.approx(0.6401, abs=1e-4)

    def test_a_neutral_site_gets_no_bonus(self):
        rows = run_ratings([g(1, T0, "bos", "nyk", 100, 110, neutral=True)],
                           k=20, h=100, c=0.6)
        assert rows[0]["home_bonus"] == 0.0
        assert rows[0]["p_home_elo"] == 0.5

    def test_the_bonus_applies_otherwise(self):
        rows = run_ratings([g(1, T0, "bos", "nyk", 100, 110)],
                           k=20, h=100, c=0.6)
        assert rows[0]["home_bonus"] == 100.0
        assert rows[0]["p_home_elo"] > 0.5


class TestTheMarginMultiplier:
    def test_the_published_values_at_zero_edge(self):
        """Amendment 5b quotes ~0.40 for a 1-goal win and ~1.16 for a
        12-point win; both are at zero rating edge."""
        assert margin_multiplier(1, 0) == pytest.approx(0.404, abs=0.005)
        assert margin_multiplier(12, 0) == pytest.approx(1.164, abs=0.005)

    def test_a_favourite_winning_big_moves_less_than_an_underdog(self):
        assert margin_multiplier(20, 300) < margin_multiplier(20, -300)

    def test_a_bigger_margin_moves_more(self):
        assert margin_multiplier(20, 0) > margin_multiplier(5, 0)

    def test_a_tie_is_refused(self):
        """Neither league leaves one on the board; a zero margin means the
        caller built the row wrong."""
        for bad in (0, -3):
            with pytest.raises(ValueError, match="margin must be positive"):
                margin_multiplier(bad, 0)


class TestTheUpdate:
    def test_it_is_zero_sum(self):
        final = final_ratings([g(1, T0, "bos", "nyk", 100, 110)],
                              k=20, h=50, c=0.6)
        assert sum(final.values()) == pytest.approx(2 * ELO_START, abs=1e-9)

    def test_the_winner_gains_and_the_loser_loses(self):
        final = final_ratings([g(1, T0, "bos", "nyk", 100, 110)],
                              k=20, h=50, c=0.6)
        assert final["nba:nyk"] > ELO_START > final["nba:bos"]

    def test_an_upset_moves_more_than_an_expected_win(self):
        upset = run_ratings([g(1, T0, "bos", "nyk", 110, 100)],
                            k=20, h=200, c=0.6)[0]
        chalk = run_ratings([g(1, T0, "bos", "nyk", 100, 110)],
                            k=20, h=200, c=0.6)[0]
        assert abs(upset["delta"]) > abs(chalk["delta"])

    def test_everyone_starts_at_1500(self):
        rows = run_ratings([g(1, T0, "bos", "nyk", 100, 110)],
                           k=20, h=50, c=0.6)
        assert rows[0]["r_home_pre"] == rows[0]["r_away_pre"] == ELO_START

    def test_k_scales_the_update(self):
        a = run_ratings([g(1, T0, "bos", "nyk", 100, 110)], k=10, h=50, c=0.6)
        b = run_ratings([g(1, T0, "bos", "nyk", 100, 110)], k=20, h=50, c=0.6)
        assert b[0]["delta"] == pytest.approx(2 * a[0]["delta"])


class TestTheAvailabilityDelay:
    """A game may only see results that were PUBLIC when it started."""

    def test_a_game_three_hours_later_does_not_see_the_earlier_result(self):
        delay = RESULT_DELAY_SECONDS["nba"]
        games = [g(1, T0, "bos", "nyk", 100, 130),
                 g(2, T0 + 3600, "nyk", "phi", 100, 110)]
        assert delay > 3600, "the premise: the first game is not over yet"
        rows = run_ratings(games, k=20, h=50, c=0.6)
        assert rows[1]["r_away_pre"] == ELO_START   # nyk has not been updated

    def test_a_game_the_next_day_does_see_it(self):
        games = [g(1, T0, "bos", "nyk", 100, 130),
                 g(2, T0 + DAY, "nyk", "phi", 100, 110)]
        rows = run_ratings(games, k=20, h=50, c=0.6)
        assert rows[1]["r_away_pre"] > ELO_START

    def test_every_update_settles_by_the_end(self):
        games = [g(1, T0, "bos", "nyk", 100, 130),
                 g(2, T0 + 3600, "nyk", "phi", 100, 110)]
        final = final_ratings(games, k=20, h=50, c=0.6)
        assert sum(final.values()) == pytest.approx(3 * ELO_START, abs=1e-9)

    def test_an_unknown_sport_gets_the_longest_delay_not_zero(self):
        games = [g(1, T0, "bos", "nyk", 1, 2, sport="wnba"),
                 g(2, T0 + max(RESULT_DELAY_SECONDS.values()) - 60,
                   "nyk", "phi", 1, 2, sport="wnba")]
        rows = run_ratings(games, k=20, h=50, c=0.6)
        assert rows[1]["r_away_pre"] == ELO_START


class TestTheSeasonCarryOver:
    def test_c_zero_is_a_fresh_start(self):
        assert carry_over(1700, 0.0) == ELO_START

    def test_c_one_would_carry_everything(self):
        assert carry_over(1700, 1.0) == 1700

    def test_it_is_applied_at_a_season_change(self):
        games = [g(1, T0, "bos", "nyk", 100, 130, season="2023-24"),
                 g(2, T0 + 400 * DAY, "bos", "nyk", 100, 110, season="2024-25")]
        rows = run_ratings(games, k=20, h=0, c=0.0)
        # c=0 pulls both back to 1500 before the second game.
        assert rows[1]["r_home_pre"] == ELO_START
        assert rows[1]["r_away_pre"] == ELO_START

    def test_a_partial_carry_over_keeps_part_of_the_edge(self):
        games = [g(1, T0, "bos", "nyk", 100, 130, season="2023-24"),
                 g(2, T0 + 400 * DAY, "bos", "nyk", 100, 110, season="2024-25")]
        full = run_ratings(games, k=20, h=0, c=1.0)
        half = run_ratings(games, k=20, h=0, c=0.5)
        gained = full[1]["r_home_pre"] - ELO_START
        assert half[1]["r_home_pre"] - ELO_START == pytest.approx(gained / 2)

    def test_no_carry_over_inside_one_season(self):
        games = [g(1, T0, "bos", "nyk", 100, 130),
                 g(2, T0 + 30 * DAY, "bos", "nyk", 100, 110)]
        rows = run_ratings(games, k=20, h=0, c=0.0)
        assert rows[1]["r_home_pre"] != ELO_START


class TestScoring:
    def test_log_loss_of_a_certain_correct_call_is_zero(self):
        assert log_loss([{"p_home_elo": 1.0, "y": 1.0}]) == pytest.approx(0, abs=1e-12)

    def test_log_loss_of_a_coinflip_is_ln_two(self):
        assert log_loss([{"p_home_elo": 0.5, "y": 1.0}]) == pytest.approx(math.log(2))

    def test_a_certain_wrong_call_is_clamped_not_infinite(self):
        """One impossible game must not decide the grid."""
        assert math.isfinite(log_loss([{"p_home_elo": 1.0, "y": 0.0}]))

    def test_brier(self):
        assert brier([{"p_home_elo": 0.75, "y": 1.0}]) == pytest.approx(0.0625)

    def test_both_refuse_an_empty_set(self):
        for fn in (log_loss, brier):
            with pytest.raises(ValueError):
                fn([])


class TestTheGrid:
    def test_the_sizes_are_the_pre_registered_ones(self):
        assert GRID_SIZE == {"nba": 140, "nhl": 105}

    def test_the_grid_is_verbatim_from_amendment_5b(self):
        assert GRID["nba"]["k"] == (10, 15, 20, 25, 30)
        assert GRID["nba"]["h"] == (50, 75, 100, 125)
        assert GRID["nhl"]["k"] == (8, 12, 16, 20, 30)
        assert GRID["nhl"]["h"] == (25, 50, 75)
        assert GRID["nba"]["c"] == GRID["nhl"]["c"] == (0.0, 0.5, 0.6, 0.7,
                                                        0.75, 0.8, 0.9)

    def test_it_scores_only_the_criterion_season(self):
        games = [g(i, T0 + i * DAY, "bos", "nyk", 100, 110, season="2023-24")
                 for i in range(4)]
        games += [g(100 + i, T0 + (400 + i) * DAY, "bos", "nyk", 100, 110)
                  for i in range(3)]
        got = grid_search(games, "nba", criterion_season="2024-25")
        assert all(r["n"] == 3 for r in got)

    def test_it_refuses_a_criterion_season_with_no_games(self):
        games = [g(1, T0, "bos", "nyk", 100, 110, season="2023-24")]
        with pytest.raises(ValueError, match="no 2024-25 games"):
            grid_search(games, "nba", criterion_season="2024-25")

    def test_ties_go_to_smaller_k_then_smaller_h_then_larger_c(self):
        """Pinned on the comparator directly: a real tie across 140 points is
        not reproducible, and the rule is what matters."""
        pts = [{"log_loss": 0.5, "k": 20, "h": 50, "c": 0.5},
               {"log_loss": 0.5, "k": 10, "h": 75, "c": 0.5},
               {"log_loss": 0.5, "k": 10, "h": 50, "c": 0.5},
               {"log_loss": 0.5, "k": 10, "h": 50, "c": 0.9}]
        pts.sort(key=lambda r: (r["log_loss"], r["k"], r["h"], -r["c"]))
        assert (pts[0]["k"], pts[0]["h"], pts[0]["c"]) == (10, 50, 0.9)

    def test_on_grid_edge_names_the_edge_parameters(self):
        assert on_grid_edge({"k": 10, "h": 75, "c": 0.5}, "nba") == ["k"]
        assert on_grid_edge({"k": 20, "h": 50, "c": 0.6}, "nba") == ["h"]
        assert on_grid_edge({"k": 16, "h": 50, "c": 0.9}, "nhl") == ["c"]


class TestTheFrozenChoice:
    """Amendment 5b freezes K, H and c by commit before any 2025-26 rating is
    computed. These pin the committed values against the published grid."""

    def test_the_chosen_points_are_on_the_grid(self):
        for sport, point in CHOSEN.items():
            for name in ("k", "h", "c"):
                assert point[name] in GRID[sport][name], (sport, name)

    def test_the_committed_values(self):
        assert CHOSEN["nba"] == {"k": 20, "h": 50, "c": 0.6}
        assert CHOSEN["nhl"] == {"k": 16, "h": 50, "c": 0.9}

    def test_both_optima_sit_on_a_grid_edge_and_that_is_disclosed(self):
        assert on_grid_edge(CHOSEN["nba"], "nba") == ["h"]
        assert on_grid_edge(CHOSEN["nhl"], "nhl") == ["c"]

    def test_the_criterion_values_are_pinned(self):
        assert CHOSEN_LOG_LOSS == {"nba": 0.60781, "nhl": 0.66618}
        assert CHOSEN_BRIER == {"nba": 0.21044, "nhl": 0.23686}

    @pytest.mark.skipif(not Path("data/ratings/grid-nba.json").is_file(),
                        reason="grid output is gitignored; run run_ratings.py")
    def test_the_frozen_values_match_the_written_grid(self):
        for sport in ("nba", "nhl"):
            doc = json.loads(Path(f"data/ratings/grid-{sport}.json")
                             .read_text(encoding="utf-8"))
            best = doc["best"]
            assert (best["k"], best["h"], best["c"]) == (
                CHOSEN[sport]["k"], CHOSEN[sport]["h"], CHOSEN[sport]["c"])
            assert round(best["log_loss"], 5) == CHOSEN_LOG_LOSS[sport]
