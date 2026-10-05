"""The slate forecast log (scripts/predict_slate.py).

Only the pure parts, which are the parts that can be wrong in a way that
matters: which records count, and the arithmetic over them. The script is
loaded by path because `scripts/` is not a package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "predict_slate",
    Path(__file__).resolve().parent.parent / "scripts" / "predict_slate.py")
ps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ps)


def rec(gid, logged_at, *, blind=True, p_home=0.6):
    return {"game_id": str(gid), "logged_at": logged_at, "blind": blind,
            "p_home": p_home}


def final(gid, winner):
    return {"game_id": str(gid), "winner": winner}


class TestWhichRecordsCount:
    def test_only_the_first_blind_record_per_game(self):
        """Re-running a date appends. Grading the best of several bites would
        turn a forecast log into a selection of one."""
        lines = [rec(1, "2026-10-05T10:00:00Z", p_home=0.60),
                 rec(1, "2026-10-05T12:00:00Z", p_home=0.90),
                 rec(1, "2026-10-05T14:00:00Z", p_home=0.20)]
        first, not_blind = ps.first_blind(lines)
        assert list(first) == ["1"]
        assert first["1"]["p_home"] == 0.60
        assert not_blind == 0

    def test_non_blind_rows_never_count(self):
        lines = [rec(1, "2026-10-04T10:00:00Z", blind=False),
                 rec(2, "2026-10-05T10:00:00Z", blind=True)]
        first, not_blind = ps.first_blind(lines)
        assert list(first) == ["2"]
        assert not_blind == 1

    def test_a_non_blind_row_does_not_shadow_a_later_blind_one(self):
        """The 10-04 exercise must not block the 10-05 forecast for the same
        game id if one were ever logged twice."""
        lines = [rec(7, "2026-10-04T10:00:00Z", blind=False, p_home=0.99),
                 rec(7, "2026-10-05T10:00:00Z", blind=True, p_home=0.55)]
        first, _ = ps.first_blind(lines)
        assert first["7"]["p_home"] == 0.55

    def test_an_empty_log_is_not_an_error(self):
        assert ps.first_blind([]) == ({}, 0)

    def test_records_are_ordered_by_log_time_not_file_order(self):
        lines = [rec(3, "2026-10-05T18:00:00Z", p_home=0.70),
                 rec(3, "2026-10-05T09:00:00Z", p_home=0.40)]
        first, _ = ps.first_blind(lines)
        assert first["3"]["p_home"] == 0.40


class TestTheArithmetic:
    def test_a_correct_home_lean_counts(self):
        g = ps.grade([(rec(1, "t", p_home=0.7), final(1, "home"))])
        assert g["hit"] == 1 and g["accuracy"] == 1.0
        assert g["brier"] == pytest.approx(0.09)

    def test_a_correct_away_lean_counts(self):
        g = ps.grade([(rec(1, "t", p_home=0.3), final(1, "away"))])
        assert g["hit"] == 1
        assert g["brier"] == pytest.approx(0.09)

    def test_the_always_home_baseline_is_reported_separately(self):
        """The whole point of the October diagnosis: the Elo's record has to
        be read against the trivial rule, not against its own expectation."""
        pairs = [(rec(1, "t", p_home=0.7), final(1, "away")),
                 (rec(2, "t", p_home=0.7), final(2, "away")),
                 (rec(3, "t", p_home=0.7), final(3, "home"))]
        g = ps.grade(pairs)
        assert g["hit"] == 1
        assert g["home_hit"] == 1
        assert g["home_accuracy"] == pytest.approx(1 / 3)

    def test_expected_correct_comes_from_the_forecasts(self):
        pairs = [(rec(1, "t", p_home=0.7), final(1, "home")),
                 (rec(2, "t", p_home=0.3), final(2, "home"))]
        assert ps.grade(pairs)["expected_correct"] == pytest.approx(1.4)

    def test_log_loss_is_finite_on_a_confident_miss(self):
        import math
        g = ps.grade([(rec(1, "t", p_home=1.0), final(1, "away"))])
        assert math.isfinite(g["log_loss"])

    def test_an_empty_grade_reports_zero_not_a_crash(self):
        assert ps.grade([]) == {"n": 0}

    def test_a_coinflip_forecast_scores_a_quarter(self):
        g = ps.grade([(rec(1, "t", p_home=0.5), final(1, "home"))])
        assert g["brier"] == pytest.approx(0.25)


def test_the_frozen_constants_are_the_ones_used():
    from chira.ratings import CHOSEN
    assert ps.CHOSEN["nhl"] == CHOSEN["nhl"]
    assert ps.SEASON == "2026-27"
