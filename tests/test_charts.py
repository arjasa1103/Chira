"""The chart layer, exercised end to end on a synthetic snapshot.

Rendering is checked for "did it produce a real figure with the right data",
not for pixels. The parts worth protecting are the ones that would ship a
WRONG chart while looking fine: the two deliberately different bin counts, and
the stacked bars adding up to the schedule.
"""

from __future__ import annotations

import numpy as np
import pytest
from test_analysis import build, g, pr

from chira.calibration import MAX_BINS, ece
from chira.charts import calibration_stats, chart_calibration, chart_coverage


@pytest.fixture
def snapshot_like():
    """Two sports, enough games per week that the identity is non-trivial."""
    rng = np.random.default_rng(3)
    games, priced, misses = [], [], []
    for sport in ("nba", "nhl"):
        for i in range(400):
            gid = f"{i:04d}"
            date = f"2024-10-{22 + (i % 9):02d}"
            p = float(rng.uniform(0.15, 0.85))
            won = "home" if rng.random() < p else "away"
            games.append(g(gid, date, won, sport=sport))
            # Every 50th game has no market, so `misses` is populated and the
            # stacked bar has a red segment to add up.
            if i % 50 == 49:
                misses.append((sport, "2024-25", gid, "no_market"))
            else:
                priced.append(pr(gid, p, sport=sport))
    return build(games, priced, misses)


class TestChartCoverage:
    def test_it_writes_a_png_and_returns_both_sports(self, snapshot_like, tmp_path):
        out = tmp_path / "c1.png"
        summary = chart_coverage(snapshot_like, out)
        assert out.is_file() and out.stat().st_size > 5000
        assert set(summary) == {"nba/2024-25", "nhl/2024-25"}

    def test_priced_plus_missed_equals_scheduled(self, snapshot_like, tmp_path):
        """The stacked bar's height is the schedule. That is the whole chart."""
        summary = chart_coverage(snapshot_like, tmp_path / "c1.png")
        for s in summary.values():
            assert s["priced"] + s["missed"] == s["scheduled"] == 400
            assert s["priced"] == 392 and s["missed"] == 8

    def test_worst_week_is_reported(self, snapshot_like, tmp_path):
        summary = chart_coverage(snapshot_like, tmp_path / "c1.png")
        w = summary["nba/2024-25"]["worst_week"]
        assert w["priced"] <= w["scheduled"]

    def test_it_creates_the_output_directory(self, snapshot_like, tmp_path):
        out = tmp_path / "nested" / "deeper" / "c1.png"
        chart_coverage(snapshot_like, out)
        assert out.is_file()


class TestChartCalibration:
    def test_it_writes_a_png_and_reports_per_sport_season(self, snapshot_like, tmp_path):
        out = tmp_path / "c2.png"
        stats = chart_calibration(snapshot_like, out, reps=50)
        assert out.is_file() and out.stat().st_size > 5000
        assert set(stats) == {"nba/2024-25", "nhl/2024-25"}
        assert stats["nba/2024-25"]["n"] == 392

    def test_look_coverage_travels_with_the_stats(self, snapshot_like, tmp_path):
        stats = chart_calibration(snapshot_like, tmp_path / "c2.png", reps=50)
        assert stats["nba/2024-25"]["look_coverage"]["p_close"]["available"] == 392

    def test_a_synthetic_calibrated_market_lands_near_the_diagonal(self, snapshot_like,
                                                                   tmp_path):
        """The fixture draws outcomes from the price, so the curve must track."""
        stats = chart_calibration(snapshot_like, tmp_path / "c2.png", reps=200)
        s = stats["nba/2024-25"]
        assert s["cox_slope"] == pytest.approx(1.0, abs=0.35)
        curve = s["curve"]
        assert len(curve["mean_p"]) == len(curve["obs_rate"]) == len(s["band_lo"])


class TestTheTwoBinCountsAreNotConfused:
    """A threshold is only comparable to the null it was simulated against."""

    def test_gate_ece_is_always_reported_at_ten_bins(self):
        rng = np.random.default_rng(1)
        p = rng.uniform(0.1, 0.9, 900)
        y = (rng.random(900) < p).astype(float)
        s = calibration_stats(p, y, reps=50)
        assert s["ece_10bin"] == ece(p, y, MAX_BINS)

    def test_chart_bins_honour_the_150_floor_and_differ_from_ten(self):
        rng = np.random.default_rng(1)
        p = rng.uniform(0.1, 0.9, 900)
        y = (rng.random(900) < p).astype(float)
        s = calibration_stats(p, y, reps=50)
        assert s["n_bins"] == 6           # 900 // 150
        assert s["ece_chart_bins"] == ece(p, y, 6)
        assert s["ece_chart_bins"] != s["ece_10bin"]

    def test_murphy_reconciles_at_the_chart_bin_count(self):
        rng = np.random.default_rng(2)
        p = rng.uniform(0.1, 0.9, 1500)
        y = (rng.random(1500) < p).astype(float)
        s = calibration_stats(p, y, reps=50)
        m = s["murphy"]
        assert m["brier_from_decomp"] == pytest.approx(m["brier_direct"], abs=5e-3)
        assert m["brier_direct"] == pytest.approx(s["brier"], abs=1e-12)

    def test_gate_flags_are_recorded_but_never_raise(self):
        """The market has NO gate authority; a tilt is reported, not enforced."""
        rng = np.random.default_rng(4)
        p = np.clip(rng.uniform(0.1, 0.9, 800) + 0.15, 0.01, 0.99)
        y = (rng.random(800) < 0.4).astype(float)
        s = calibration_stats(p, y, reps=50)   # must not raise
        assert s["ece_10bin_within_gate"] is False
        assert isinstance(s["slope_ci_inside_band"], bool)
