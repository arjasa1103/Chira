"""Headline 2's strata, the primary test, and the artifact checks around it.

Offline and synthetic. The frames here are built so the right answer is known
by construction, which is the only way to test a design whose whole purpose is
to stop a confound from producing a finding.
"""

from __future__ import annotations

import numpy as np
import pytest

from chira.strata import (
    ABSENT,
    LEVELS,
    PHASES,
    assign_strata,
    caliper_match,
    cell_stats,
    cell_table,
    null_reference,
    primary_test,
    range_sensitivity,
    sensitivity,
    slope_difference,
)


def make_frame(n=800, *, sport="nba", season="2024-25", weeks=20, seed=0,
               volume_rises_with_week=True, absent=0, slope=1.0):
    """A frame with the same keys `analysis.frame` produces.

    `volume_rises_with_week` reproduces the week-4 finding that forced
    Amendment 3a: volume climbs steeply through a season, which is what makes
    the pre-registered within-season cut confounded with season phase.
    """
    rng = np.random.default_rng(seed)
    week = rng.integers(1, weeks + 1, n)
    base = week * 1000.0 if volume_rises_with_week else np.full(n, 1000.0)
    volume = base * rng.lognormal(0, 0.35, n)
    if absent:
        volume[rng.choice(n, absent, replace=False)] = np.nan
    p = rng.uniform(0.08, 0.92, n)
    from scipy.special import expit, logit
    truth = expit(slope * logit(p))
    f = {
        "sport": np.array([sport] * n, dtype=object),
        "season": np.array([season] * n, dtype=object),
        "game_id": np.array([f"{i:05d}" for i in range(n)], dtype=object),
        "week_of_season": week.astype(int),
        "volume": volume,
        "volume_source": np.array(["market"] * n, dtype=object),
        "p_close": p,
        "p_t1h": p.copy(), "p_t6h": p.copy(), "p_t24h": p.copy(),
        "y": (rng.random(n) < truth).astype(float),
        "stale_flat_run": np.array([bool(v) for v in rng.random(n) < 0.4]),
    }
    return f


class TestStrataAssignment:
    def test_both_axes_are_equal_count_median_splits(self):
        f = make_frame(n=600)
        assign_strata(f)
        assert set(f["phase"]) <= set(PHASES)
        # four cells, each roughly a quarter
        for ph in PHASES:
            for lv in LEVELS:
                n = int(((f["phase"] == ph) & (f["liquidity"] == lv)).sum())
                assert 100 < n < 200, (ph, lv, n)

    def test_ties_go_to_the_early_and_low_side_deterministically(self):
        """Week-of-season is a small integer, so a whole week sits on the median."""
        f = make_frame(n=400, weeks=4)
        assign_strata(f)
        med = float(np.median(f["week_of_season"]))
        on_median = f["week_of_season"] == med
        assert on_median.sum() > 0
        assert set(f["phase"][on_median]) == {"early"}

    def test_cut_points_are_recorded_per_sport_season(self):
        f = make_frame(n=400)
        cuts = assign_strata(f)
        rec = cuts["nba/2024-25"]
        assert rec["week_median"] > 0
        assert rec["volume_median_early"] < rec["volume_median_late"]

    def test_each_sport_season_is_cut_independently(self):
        a = make_frame(n=300, season="2024-25", seed=1)
        b = make_frame(n=300, season="2025-26", seed=2)
        # a frame holding both, still canonically ordered by construction
        f = {k: np.concatenate([a[k], b[k]]) for k in a}
        cuts = assign_strata(f)
        assert set(cuts) == {"nba/2024-25", "nba/2025-26"}
        for season in ("2024-25", "2025-26"):
            m = f["season"] == season
            for lv in LEVELS:
                # each level spans both phases, so ~half of that season's 300
                assert 120 < int((m & (f["liquidity"] == lv)).sum()) < 180

    def test_games_without_volume_get_no_liquidity_and_are_counted(self):
        f = make_frame(n=400, absent=40)
        cuts = assign_strata(f)
        assert cuts["nba/2024-25"]["n_volume_absent"] == 40
        assert int((f["liquidity"] == ABSENT).sum()) == 40
        assert np.all(np.isnan(f["volume"][f["liquidity"] == ABSENT]))

    def test_absent_volume_games_keep_their_phase(self):
        """Amendment 4: they leave the liquidity axis, not the analysis."""
        f = make_frame(n=400, absent=40)
        assign_strata(f)
        absent = f["liquidity"] == ABSENT
        assert set(f["phase"][absent]) <= set(PHASES)
        assert "" not in set(f["phase"][absent])


class TestAmendment3aActuallyRemovesTheConfound:
    """The claim 3a rests on, tested on data built to contain the confound.

    Measured on the census: cutting volume within SEASON left 66-72% of
    low-liquidity games in the early phase, because volume climbs through a
    season. Cutting within PHASE restored 0.503-0.534. If this test ever fails,
    3a's reasoning is wrong and headline 2's primary test is confounded again.
    """

    def test_the_within_season_cut_is_confounded(self):
        f = make_frame(n=1200, volume_rises_with_week=True, seed=7)
        assign_strata(f)
        early = f["phase"] == "early"
        # the PRE-REGISTERED cut: median over the whole season
        low_season = f["volume"] <= np.nanmedian(f["volume"])
        share_early = float(np.mean(early[low_season]))
        assert share_early > 0.60, (
            f"the confound should be present in this fixture, got {share_early:.3f}")

    def test_the_within_phase_cut_removes_it(self):
        f = make_frame(n=1200, volume_rises_with_week=True, seed=7)
        assign_strata(f)
        early = f["phase"] == "early"
        low_phase = f["liquidity"] == "low"
        share_early = float(np.mean(early[low_phase]))
        assert 0.45 < share_early < 0.55, (
            f"within-phase cutting should be ~balanced, got {share_early:.3f}")

    def test_it_is_the_cut_and_not_the_fixture(self):
        """With flat volume the within-season cut is NOT confounded.

        The control is the population's own early share, not 0.5: ties go to
        the early side and weeks are integers, so the whole median week lands
        in `early` and the population share is ~0.56. Comparing against 0.5
        would be testing the tie rule, not the confound.
        """
        f = make_frame(n=1200, volume_rises_with_week=False, seed=7)
        assign_strata(f)
        early = f["phase"] == "early"
        population = float(np.mean(early))
        low_season = f["volume"] <= np.nanmedian(f["volume"])
        assert abs(float(np.mean(early[low_season])) - population) < 0.05


class TestNullReference:
    def test_it_picks_the_largest_row_at_or_below_n(self):
        assert null_reference("nba", 700)["reference_n"] == 613
        assert null_reference("nba", 613)["reference_n"] == 613
        assert null_reference("nhl", 500)["reference_n"] == 448

    def test_every_real_cell_size_is_inside_the_table(self):
        """NBA cells reach 212 and NHL 221; an n=200 row was simulated for that."""
        for sport, n in (("nba", 212), ("nba", 299), ("nhl", 221), ("nhl", 225)):
            assert null_reference(sport, n)["below_table"] is False

    def test_below_the_table_it_says_so(self):
        ref = null_reference("nba", 50)
        assert ref["below_table"] is True
        assert ref["reference_n"] == 200

    def test_every_tabulated_row_resolves_in_both_tables(self):
        """null_reference picks its n from the ECE table and indexes the SLOPE
        table with it, so a row in one and not the other is a KeyError raised
        mid-analysis on whichever cell lands on it."""
        from chira.constants import (
            CENSUS_NULL_ECE_P99_BY_N,
            CENSUS_NULL_SLOPE_CI_BY_N,
        )

        assert set(CENSUS_NULL_ECE_P99_BY_N) == set(CENSUS_NULL_SLOPE_CI_BY_N)
        for sport, n in CENSUS_NULL_ECE_P99_BY_N:
            ref = null_reference(sport, n)
            assert ref["reference_n"] == n
            assert ref["slope_ci"][0] < ref["slope_ci"][1]

    def test_the_small_n_null_is_wide_enough_to_matter(self):
        """At n=225 the null ECE p99 is 4x the pooled cap. That IS the finding."""
        assert null_reference("nhl", 225)["ece_p99"] > 0.12
        lo, hi = null_reference("nhl", 225)["slope_ci"]
        assert lo < 0.5 and hi > 1.6


class TestCellStats:
    def test_resolution_is_not_an_artifact_of_one_bin(self):
        """A cell of ~300 gets n_bins_for = 2, and resolution with 1 bin is 0."""
        rng = np.random.default_rng(3)
        p = rng.uniform(0.1, 0.9, 300)
        y = (rng.random(300) < p).astype(float)
        stats = cell_stats(p, y, "nba")
        assert stats["resolution"] > 0.01, "identically zero means the bin count won"

    def test_the_own_n_null_travels_with_the_number(self):
        rng = np.random.default_rng(4)
        p = rng.uniform(0.1, 0.9, 250)
        y = (rng.random(250) < p).astype(float)
        stats = cell_stats(p, y, "nba")
        assert stats["null"]["reference_n"] == 200
        assert stats["ece_inside_own_null"] in (True, False)

    def test_a_cell_table_covers_every_populated_cell(self):
        f = make_frame(n=800)
        assign_strata(f)
        rows = cell_table(f)
        assert len(rows) == 4
        assert {(r["phase"], r["liquidity"]) for r in rows} == {
            (ph, lv) for ph in PHASES for lv in LEVELS}


class TestSlopeDifference:
    def test_it_recovers_a_difference_built_into_the_data(self):
        from scipy.special import expit, logit
        rng = np.random.default_rng(5)
        p_low = rng.uniform(0.08, 0.92, 1200)
        p_high = rng.uniform(0.08, 0.92, 1200)
        # low stratum underconfident (true slope 1.4), high one calibrated
        y_low = (rng.random(1200) < expit(1.4 * logit(p_low))).astype(float)
        y_high = (rng.random(1200) < p_high).astype(float)
        r = slope_difference(p_low, y_low, p_high, y_high, reps=400, seed=1)
        assert r["difference"] > 0.15
        assert r["ci_lo"] < r["difference"] < r["ci_hi"]
        assert r["excludes_zero"] is True

    def test_no_difference_gives_an_interval_containing_zero(self):
        rng = np.random.default_rng(6)
        p_low = rng.uniform(0.08, 0.92, 1000)
        p_high = rng.uniform(0.08, 0.92, 1000)
        y_low = (rng.random(1000) < p_low).astype(float)
        y_high = (rng.random(1000) < p_high).astype(float)
        r = slope_difference(p_low, y_low, p_high, y_high, reps=400, seed=1)
        assert r["ci_lo"] < 0 < r["ci_hi"]
        assert r["excludes_zero"] is False

    def test_the_bootstrap_keeps_each_group_at_its_own_size(self):
        rng = np.random.default_rng(7)
        p_low, p_high = rng.uniform(0.1, 0.9, 400), rng.uniform(0.1, 0.9, 900)
        y_low = (rng.random(400) < p_low).astype(float)
        y_high = (rng.random(900) < p_high).astype(float)
        r = slope_difference(p_low, y_low, p_high, y_high, reps=100, seed=1)
        assert r["n_low"] == 400 and r["n_high"] == 900

    def test_it_is_deterministic_for_a_fixed_seed(self):
        rng = np.random.default_rng(8)
        p_low, p_high = rng.uniform(0.1, 0.9, 500), rng.uniform(0.1, 0.9, 500)
        y_low = (rng.random(500) < p_low).astype(float)
        y_high = (rng.random(500) < p_high).astype(float)
        a = slope_difference(p_low, y_low, p_high, y_high, reps=100, seed=3)
        b = slope_difference(p_low, y_low, p_high, y_high, reps=100, seed=3)
        assert a["ci_lo"] == b["ci_lo"] and a["ci_hi"] == b["ci_hi"]

    def test_an_unfittable_stratum_reports_instead_of_inventing_a_number(self):
        p_low = np.full(200, 0.6)            # constant price: no slope exists
        y_low = (np.arange(200) < 120).astype(float)
        rng = np.random.default_rng(9)
        p_high = rng.uniform(0.1, 0.9, 200)
        y_high = (rng.random(200) < p_high).astype(float)
        r = slope_difference(p_low, y_low, p_high, y_high, reps=50, seed=1)
        assert r["difference"] is None
        assert "not identified" in r["error"]

    def test_too_many_failed_replicates_refuses_the_interval(self, monkeypatch):
        import chira.strata as st

        def always_fails(p, y):
            raise ValueError("synthetic")

        rng = np.random.default_rng(10)
        p_low, p_high = rng.uniform(0.1, 0.9, 200), rng.uniform(0.1, 0.9, 200)
        y_low = (rng.random(200) < p_low).astype(float)
        y_high = (rng.random(200) < p_high).astype(float)
        real = st.cox_slope_intercept
        calls = {"n": 0}

        def flaky(p, y):
            calls["n"] += 1
            return real(p, y) if calls["n"] <= 2 else always_fails(p, y)

        monkeypatch.setattr(st, "cox_slope_intercept", flaky)
        with pytest.raises(ValueError, match="conditioned on convergence"):
            slope_difference(p_low, y_low, p_high, y_high, reps=100, seed=1)


class TestPriceRangeArtifactCheck:
    """Volume is outcome-correlated, so the contrast might be a range effect."""

    def test_caliper_matching_equalises_the_price_spread(self):
        from scipy.special import logit
        f = make_frame(n=1200, seed=11)
        assign_strata(f)
        il, ih = caliper_match(f, "nba")
        assert len(il) > 100
        sd_low = np.std(np.abs(logit(np.clip(f["p_close"][il], 1e-6, 1 - 1e-6))))
        sd_high = np.std(np.abs(logit(np.clip(f["p_close"][ih], 1e-6, 1 - 1e-6))))
        assert abs(sd_low - sd_high) < 0.05

    def test_matching_is_one_to_one_without_replacement(self):
        f = make_frame(n=800, seed=12)
        assign_strata(f)
        il, ih = caliper_match(f, "nba")
        assert len(set(ih.tolist())) == len(ih)
        assert len(set(il.tolist())) == len(il)
        assert len(il) == len(ih)

    def test_matching_is_deterministic(self):
        f = make_frame(n=600, seed=13)
        assign_strata(f)
        a = caliper_match(f, "nba")
        b = caliper_match(f, "nba")
        assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])

    def test_it_only_matches_within_the_caliper(self):
        from scipy.special import logit
        f = make_frame(n=600, seed=14)
        assign_strata(f)
        il, ih = caliper_match(f, "nba", caliper=0.02)
        d = np.abs(np.abs(logit(np.clip(f["p_close"][il], 1e-6, 1 - 1e-6)))
                   - np.abs(logit(np.clip(f["p_close"][ih], 1e-6, 1 - 1e-6))))
        assert np.all(d <= 0.02 + 1e-9)

    def test_range_sensitivity_reports_dispersion_and_bands(self):
        f = make_frame(n=900, seed=15)
        assign_strata(f)
        out = range_sensitivity(f, reps=200)
        assert set(out["dispersion"]) == set(LEVELS)
        assert "0.2-0.8" in out["bands"]
        assert out["caliper_matched"]["pairs"] > 50


class TestSensitivityAndPrimary:
    def test_absent_volume_games_never_enter_a_liquidity_sample(self):
        f = make_frame(n=800, absent=80, seed=16)
        assign_strata(f)
        out = sensitivity(f, reps=100)
        assert out["volume_absent"]["n"] == 80
        counted = out["by_look"]["p_close"]
        assert counted["n_low"] + counted["n_high"] == 800 - 80

    def test_the_four_looks_are_reported_separately(self):
        """They are four looks at ONE sample; one combined interval would lie."""
        f = make_frame(n=700, seed=17)
        assign_strata(f)
        out = sensitivity(f, reps=100)
        assert set(out["by_look"]) == {"p_close", "p_t1h", "p_t6h", "p_t24h"}

    def test_staleness_splits_partition_the_sample(self):
        f = make_frame(n=700, seed=18)
        assign_strata(f)
        out = sensitivity(f, reps=100)
        stale, fresh = out["by_staleness"]["stale"], out["by_staleness"]["fresh"]
        total = (stale["n_low"] + stale["n_high"]
                 + fresh["n_low"] + fresh["n_high"])
        assert total == 700

    def test_the_primary_test_is_nba_and_carries_its_own_label(self):
        f = make_frame(n=800, seed=19)
        assign_strata(f)
        out = primary_test(f, reps=200)
        assert out["sport"] == "nba" and out["primary"] is True
        assert out["look"] == "p_close"
        assert "2024-25" in out["per_season"]

    def test_the_primary_test_ignores_the_other_sport(self):
        nba = make_frame(n=400, sport="nba", seed=20)
        nhl = make_frame(n=400, sport="nhl", seed=21)
        f = {k: np.concatenate([nba[k], nhl[k]]) for k in nba}
        assign_strata(f)
        out = primary_test(f, reps=100)
        assert out["pooled"]["n_low"] + out["pooled"]["n_high"] == 400
