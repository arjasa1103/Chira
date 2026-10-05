"""Stage 1a's proxy fitness gate (notes/profit-stage1-spec.md section 3).

The gate is a pre-committed threshold, so the thing worth testing is that the
machinery around it cannot quietly move: the rank correlation, the gate
constant, and the refusal to run on the sealed season.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_stage1a_rho",
    Path(__file__).resolve().parent.parent / "scripts" / "run_stage1a_rho.py")
s1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(s1)


class TestTheGateConstants:
    def test_the_threshold_is_the_pre_committed_one(self):
        """Section 3: rho < 0.5 kills. If this ever changes, the
        pre-commitment is void and the note must say so."""
        assert s1.RHO_GATE == 0.5

    def test_the_proxy_horizon_is_six_hours(self):
        assert s1.PROXY_HORIZON_SECONDS == 6 * 3600

    def test_the_sql_filters_before_the_window(self):
        """Ordering all 145.6M price points is the spill that broke week 3's
        ORDER BY. The scan must be cut down first."""
        sql = s1._PROXY_SQL
        window_at = sql.index("OVER (PARTITION BY")
        for clause in ("side = 'home'", "pp.sport = ?", "pp.t <= c.tip_t"):
            assert clause in sql[:window_at], clause


class TestTheRankCorrelation:
    def test_a_perfect_monotone_relation_is_one(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert s1.spearman(x, x * 3 + 1) == pytest.approx(1.0)

    def test_a_reversed_relation_is_minus_one(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert s1.spearman(x, -x) == pytest.approx(-1.0)

    def test_it_is_rank_based_not_linear(self):
        """A monotone but wildly non-linear relation still scores 1."""
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert s1.spearman(x, np.exp(x * 4)) == pytest.approx(1.0)

    def test_ties_get_average_ranks(self):
        """Change counts tie heavily. With average ranks a tied pair is
        symmetric, so aligned ties give +1 and opposed ties give exactly -1.
        Ranking ties by first-seen order would give neither."""
        a = np.array([1.0, 1.0, 2.0, 2.0])
        b = np.array([5.0, 5.0, 9.0, 9.0])
        assert s1.spearman(a, b) == pytest.approx(1.0)
        assert s1.spearman(a, b[::-1]) == pytest.approx(-1.0)

    def test_a_tied_block_does_not_depend_on_its_internal_order(self):
        a = np.array([1.0, 1.0, 1.0, 2.0])
        b = np.array([7.0, 3.0, 5.0, 9.0])
        first = s1.spearman(a, b)
        assert s1.spearman(a, np.array([3.0, 5.0, 7.0, 9.0])) == \
            pytest.approx(first)

    def test_row_order_does_not_change_the_answer(self):
        rng = np.random.default_rng(0)
        a = rng.integers(0, 10, 200).astype(float)
        b = rng.integers(0, 10, 200).astype(float)
        first = s1.spearman(a, b)
        p = rng.permutation(200)
        assert s1.spearman(a[p], b[p]) == pytest.approx(first)

    def test_a_constant_column_does_not_crash(self):
        got = s1.spearman(np.ones(10), np.arange(10.0))
        assert np.isnan(got) or abs(got) <= 1.0


def test_the_measured_verdict_is_recorded_and_is_a_kill():
    """Pins the published number so a later refactor cannot silently revive
    a signal the pre-commitment killed."""
    import json
    p = Path(__file__).resolve().parent.parent / "data" / "stage1a" \
        / "rho-nba-2024-25.json"
    if not p.is_file():
        pytest.skip("data/ is gitignored; run scripts/run_stage1a_rho.py")
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["verdict"] == "kill"
    assert doc["rho"] < s1.RHO_GATE
    assert round(doc["rho"], 4) == 0.2467


class TestThePrizeSettlement:
    """Section 5's bet rule and settlement, as the --prize mode applies them."""

    def test_a_bet_needs_fair_above_price_plus_costs(self):
        take, _ = s1.settle(np.array([0.50, 0.50]), np.array([0.53, 0.55]),
                               np.array([True, True]), half_spread=0.02,
                               fee_rate=0.05)
        # 0.50 + 0.02 + 0.05*0.25 = 0.5325
        assert take.tolist() == [False, True]

    def test_a_win_pays_one_over_price_paid_minus_one(self):
        _, pnl = s1.settle(np.array([0.40, 0.40]), np.array([0.9, 0.9]),
                              np.array([True, False]), half_spread=0.0,
                              fee_rate=0.0)
        assert pnl[0] == pytest.approx(1 / 0.40 - 1) and pnl[1] == -1.0
