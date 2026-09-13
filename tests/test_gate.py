"""Tests for the census validation gate.

Two of the gate's five checks exist to test the other tests, so these tests
have to make them fail on purpose:

  - `fault_injection` must fire when the store is deliberately corrupted. An
    assert nobody has watched fail is an assert nobody knows is wired up.
  - `shuffled_join` must collapse when the join is broken, AND must refuse to
    pass when the label column is so degenerate that it has no power.
"""

from __future__ import annotations

import pytest

from chira.gate import (
    MIN_DISCRIMINATION_SIGMA,
    check_complementarity,
    check_fault_injection,
    check_label_agreement,
    check_price_discriminates,
    check_price_series,
    check_reconciliation,
    check_shuffled_join,
    coverage,
    format_report,
    run_gate,
)
from chira.store import Store


def seed(store, n=60, *, home_rate=0.55, sport="nba", season="2024-25",
         market_flip=0, complement=True):
    """n scheduled games, all priced. `market_flip` breaks that many labels.

    The winner column is built from a rank fraction over n, not `i % 100`. The
    modulo version only meant what it said when n was a multiple of 100: measured
    realized home rates were 1.000 at n=10 and n=40 and 0.933 at n=60, so every
    gate test below n=100 was silently running against a degenerate label column.
    """
    n_home = round(home_rate * n)
    games, flipped = [], 0
    for i in range(n):
        winner = "home" if i < n_home else "away"
        games.append({"game_id": f"g{i:03d}", "et_date": "2025-01-15",
                      "away": "lal", "home": "bos", "away_pts": 1, "home_pts": 2,
                      "winner": winner})
    store.put_games(sport, season, games)
    for i, g in enumerate(games):
        market_winner = g["winner"]
        if flipped < market_flip:
            market_winner = "away" if g["winner"] == "home" else "home"
            flipped += 1
        agreement = "agree" if market_winner == g["winner"] else "disagree"
        # Prices must actually discriminate: a constant 0.6 for every game is
        # not what a market looks like, and it made the token-leg check
        # untestable. Home wins draw from the high side, away wins from the low.
        price = 0.62 + (i % 7) * 0.02 if g["winner"] == "home" else 0.44 - (i % 7) * 0.02
        store.put_priced(sport, season, g["game_id"], {
            "slug": f"nba-lal-bos-{g['game_id']}", "convention": "et",
            "p_home_close": round(price, 4), "n_pre_tipoff": 500, "secs_before_tip": 30,
            "label_agreement": agreement, "market_winner": market_winner,
            "complement_ok": complement if complement is not None else None,
            "complement_sum": 1.0 if complement else 0.7,
        }, points={"home": [{"t": 1_700_000_000, "p": round(price, 4)}],
                   "away": [{"t": 1_700_000_000, "p": round(1 - price, 4)}]})
    realized = sum(g["winner"] == "home" for g in games) / len(games)
    assert abs(realized - home_rate) < 1.0 / len(games) + 1e-9, (
        f"fixture drifted from its own parameter: asked {home_rate}, got {realized}")
    return games


@pytest.fixture
def store():
    s = Store()
    yield s
    s.close()


class TestLabelAgreement:
    def test_all_agree_passes(self, store):
        seed(store)
        c = check_label_agreement(store, "nba", "2024-25")
        assert c["passed"] and c["by_value"] == {"agree": 60}

    def test_a_disagreement_in_the_misses_table_fails_the_check(self, store):
        seed(store, n=60)
        store.put_miss("nba", "2024-25", "g000", "label_disagreement", ["s"])
        c = check_label_agreement(store, "nba", "2024-25")
        assert not c["passed"] and c["disagreements_in_misses"] == 1

    def test_zero_priced_rows_does_not_pass(self, store):
        """An empty sample must never certify the instrument."""
        assert not check_label_agreement(store, "nba", "2024-25")["passed"]


class TestComplementarity:
    def test_all_checked_ok_passes(self, store):
        seed(store)
        c = check_complementarity(store, "nba", "2024-25")
        assert c["passed"] and c["checked_ok"] == 60 and c["failed"] == 0

    def test_a_failure_row_fails_the_check(self, store):
        seed(store)
        store.put_miss("nba", "2024-25", "g000", "complementarity_failed", ["s"])
        assert not check_complementarity(store, "nba", "2024-25")["passed"]

    def test_an_unchecked_game_is_counted_not_silently_passed(self, store):
        seed(store, n=10, complement=None)
        c = check_complementarity(store, "nba", "2024-25")
        assert c["unchecked_no_away_series"] == 10
        assert not c["passed"], "zero checked rows cannot pass"

    def test_a_mostly_unchecked_population_does_not_pass(self, store):
        """`checked > 0` was not a gate: one verified row of 200 passed."""
        games = seed(store, n=200)
        for g in games[1:]:
            store.db.execute(
                "UPDATE priced SET complement_ok=NULL, complement_sum=NULL "
                "WHERE sport='nba' AND season='2024-25' AND game_id=?", [g["game_id"]])
        c = check_complementarity(store, "nba", "2024-25")
        assert c["checked_ok"] == 1 and c["unchecked_no_away_series"] == 199
        assert not c["passed"], "one verified row of 200 cannot certify complementarity"


class TestReconciliation:
    def test_a_full_pass_passes(self, store):
        seed(store)
        assert check_reconciliation(store, "nba", "2024-25")["passed"]

    def test_a_slice_fails_the_complete_check(self, store):
        seed(store, n=60)
        store.put_games("nba", "2024-25", [
            {"game_id": "unattempted", "et_date": "2025-02-01", "away": "lal",
             "home": "bos", "winner": "home"}])
        assert not check_reconciliation(store, "nba", "2024-25")["passed"]
        assert check_reconciliation(store, "nba", "2024-25",
                                    require_complete=False)["passed"]

    def test_the_slice_report_omits_balanced_so_it_cannot_be_misread(self, store):
        seed(store, n=60)
        c = check_reconciliation(store, "nba", "2024-25", require_complete=False)
        assert "balanced" not in c and c["partial_pass"] is True


class TestPriceSeries:
    def test_every_priced_game_with_a_series_passes(self, store):
        seed(store, n=40)
        c = check_price_series(store, "nba", "2024-25")
        assert c["passed"] and c["series"] == 80

    def test_a_priced_game_without_its_series_fails(self, store):
        """It would ship an empty raw series in the snapshot, silently."""
        seed(store, n=40)
        store.db.execute("DELETE FROM price_points WHERE game_id='g007'")
        c = check_price_series(store, "nba", "2024-25")
        assert not c["passed"] and c["priced_missing_series"] == 1

    def test_an_orphan_series_fails(self, store):
        seed(store, n=40)
        store.db.execute("DELETE FROM priced WHERE game_id='g007'")
        assert not check_price_series(store, "nba", "2024-25")["passed"]


class TestFaultInjection:
    def test_both_injections_fire_and_the_store_is_restored(self, store):
        seed(store)
        before = store.digest()
        c = check_fault_injection(store, "nba", "2024-25")
        assert c["passed"], c
        assert c["double_count_caught"] and c["lost_game_caught"]
        assert store.digest() == before

    def test_a_lost_game_fails_the_gate_on_a_SLICE(self, store):
        """The failure the old gate could not see.

        On a slice `pending > 0` is expected, so a priced row deleted outright
        just made pending one larger and every check stayed green -- while the
        coverage ratio the whole project turns on had silently moved.
        """
        seed(store, n=200)
        store.put_games("nba", "2024-25", [
            {"game_id": "unattempted", "et_date": "2025-02-01", "away": "lal",
             "home": "bos", "winner": "home"}])
        attempted = store.attempted_game_ids("nba", "2024-25")
        assert store.assert_attempted_settled("nba", "2024-25", attempted) == 200
        store.db.execute(
            "DELETE FROM priced WHERE sport='nba' AND season='2024-25' AND game_id='g050'")
        with pytest.raises(AssertionError, match="NEITHER table"):
            store.assert_attempted_settled("nba", "2024-25", attempted)

    def test_it_cannot_pass_with_nothing_to_injure(self, store):
        c = check_fault_injection(store, "nba", "2024-25")
        assert not c["passed"] and "no priced rows" in c["error"]

    def test_the_injected_row_does_not_survive(self, store):
        seed(store)
        check_fault_injection(store, "nba", "2024-25")
        slugs = [r["slug"] for r in store.priced_rows("nba", "2024-25")]
        assert "injected" not in slugs
        assert store.miss_reasons("nba", "2024-25") == {}


class TestPriceDiscriminates:
    """The link label agreement does not test: clobTokenIds aligned with outcomes."""

    def test_a_real_market_discriminates(self, store):
        seed(store, n=200)
        c = check_price_discriminates(store, "nba", "2024-25")
        assert c["passed"] and c["gap"] > 0 and c["sigma"] >= 3.0

    def test_a_flipped_token_leg_is_caught(self, store):
        """p_home_close silently carrying the AWAY probability. Nothing else
        in the gate moves: labels still agree, complementarity still passes."""
        seed(store, n=200)
        store.db.execute(
            "UPDATE priced SET p_home_close = 1.0 - p_home_close "
            "WHERE sport='nba' AND season='2024-25'")
        c = check_price_discriminates(store, "nba", "2024-25")
        assert not c["passed"] and c["gap"] < 0
        assert check_label_agreement(store, "nba", "2024-25")["passed"], \
            "label agreement is blind to this, which is why the check exists"

    def test_a_constant_price_column_is_caught(self, store):
        seed(store, n=200)
        store.db.execute("UPDATE priced SET p_home_close = 0.55")
        assert not check_price_discriminates(store, "nba", "2024-25")["passed"]

    def test_too_few_rows_is_refused(self, store):
        seed(store, n=10)
        assert not check_price_discriminates(store, "nba", "2024-25")["passed"]

    def test_the_threshold_sits_below_every_measured_sport_season(self):
        """The constant is derived from data, not taste.

        An eyeballed 3.0 failed both NHL seasons on correct data. Same defect as
        rounding a calibration gate inward from its own null: the gate fires on a
        working pipeline. Minimum measured sigma is NHL 2024-25 at 2.73.
        """
        measured = {"nba 2024-25": 5.88, "nba 2025-26": 7.60,
                    "nhl 2024-25": 2.73, "nhl 2025-26": 2.95}
        assert min(measured.values()) > MIN_DISCRIMINATION_SIGMA, (
            f"threshold {MIN_DISCRIMINATION_SIGMA} would fail "
            f"{[k for k, v in measured.items() if v <= MIN_DISCRIMINATION_SIGMA]}")
        assert MIN_DISCRIMINATION_SIGMA >= 2.0, "and it must still catch a flat column"


class TestShuffledJoin:
    def test_a_real_join_passes_and_the_shuffle_collapses_to_chance(self, store):
        seed(store, n=200, home_rate=0.55)
        c = check_shuffled_join(store, "nba", "2024-25")
        assert c["passed"]
        assert c["true_rate"] == 1.0
        assert c["shuffled_rate"] < 0.9, c

    def test_a_broken_join_fails(self, store):
        seed(store, n=200, market_flip=20)
        c = check_shuffled_join(store, "nba", "2024-25")
        assert not c["passed"] and c["true_rate"] < 1.0

    def test_a_degenerate_label_column_is_refused_rather_than_passed(self, store):
        """Every game labelled 'home': the shuffle has no power.

        true, chance and shuffled agreement are all 1.0, so the check would
        pass while proving nothing. That is the same defect as an identity test
        that cannot detect the misalignment it claims to guard.
        """
        seed(store, n=200, home_rate=1.0)
        c = check_shuffled_join(store, "nba", "2024-25")
        assert not c["passed"]
        assert "no power" in c["error"]

    def test_a_shuffle_that_does_not_shuffle_is_caught_by_the_tolerance(self, store):
        """Drives `within` to False, the branch no other test reaches.

        Without this the entire chance/SE/tolerance computation could be wrong in
        any direction and the suite would stay green, because on real data
        true_rate is 1.0 by construction and the permutation always lands near
        chance.
        """
        import random
        seed(store, n=200, home_rate=0.55)
        original = random.Random.sample
        random.Random.sample = lambda self, pop, k: list(pop)
        try:
            c = check_shuffled_join(store, "nba", "2024-25")
        finally:
            random.Random.sample = original
        assert not c["passed"]
        assert c["shuffled_within_tolerance"] is False

    def test_too_few_rows_is_refused(self, store):
        seed(store, n=10)
        c = check_shuffled_join(store, "nba", "2024-25")
        assert not c["passed"] and "need >= 30" in c["error"]


class TestWholeGate:
    def test_a_clean_slice_passes_every_check(self, store):
        seed(store, n=200)
        result = run_gate(store, "nba", "2024-25")
        assert result["passed"], format_report(result)
        assert [c["name"] for c in result["checks"]] == [
            "label_agreement", "complementarity", "reconciliation", "price_series",
            "fault_injection", "price_discriminates", "shuffled_join"]

    def test_one_bad_label_fails_the_whole_gate(self, store):
        seed(store, n=200, market_flip=1)
        assert not run_gate(store, "nba", "2024-25")["passed"]

    def test_the_report_names_the_failing_check(self, store):
        seed(store, n=200, market_flip=1)
        report = format_report(run_gate(store, "nba", "2024-25"))
        assert "FAIL" in report and "shuffled_join" in report

    def test_coverage_reports_conventions_and_reasons(self, store):
        seed(store, n=40)
        store.put_games("nba", "2024-25", [
            {"game_id": "m1", "et_date": "2025-02-01", "away": "lal",
             "home": "bos", "winner": "home"}])
        store.put_miss("nba", "2024-25", "m1", "no_market", ["a", "b"])
        cov = coverage(store, "nba", "2024-25")
        assert cov["conventions"] == {"et": 40}
        assert cov["miss_reasons"] == {"no_market": 1}
        assert cov["coverage_of_attempted"] == round(40 / 41, 4)
