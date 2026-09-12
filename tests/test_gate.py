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
    check_complementarity,
    check_fault_injection,
    check_label_agreement,
    check_reconciliation,
    check_shuffled_join,
    coverage,
    format_report,
    run_gate,
)
from chira.store import Store


def seed(store, n=60, *, home_rate=0.55, sport="nba", season="2024-25",
         market_flip=0, complement=True):
    """n scheduled games, all priced. `market_flip` breaks that many labels."""
    games, flipped = [], 0
    for i in range(n):
        winner = "home" if (i % 100) < home_rate * 100 else "away"
        games.append({"game_id": f"g{i:03d}", "et_date": "2025-01-15",
                      "away": "lal", "home": "bos", "away_pts": 1, "home_pts": 2,
                      "winner": winner})
    store.put_games(sport, season, games)
    for g in games:
        market_winner = g["winner"]
        if flipped < market_flip:
            market_winner = "away" if g["winner"] == "home" else "home"
            flipped += 1
        agreement = "agree" if market_winner == g["winner"] else "disagree"
        store.put_priced(sport, season, g["game_id"], {
            "slug": f"nba-lal-bos-{g['game_id']}", "convention": "et",
            "p_home_close": 0.6, "n_pre_tipoff": 500, "secs_before_tip": 30,
            "label_agreement": agreement, "market_winner": market_winner,
            "complement_ok": complement if complement is not None else None,
            "complement_sum": 1.0 if complement else 0.7,
        })
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


class TestFaultInjection:
    def test_the_assert_fires_and_the_store_is_restored(self, store):
        seed(store)
        before = store.digest()
        c = check_fault_injection(store, "nba", "2024-25")
        assert c["passed"] and c["assert_fired"] and c["store_restored"]
        assert store.digest() == before

    def test_it_cannot_pass_with_nothing_to_injure(self, store):
        c = check_fault_injection(store, "nba", "2024-25")
        assert not c["passed"] and "no priced rows" in c["error"]

    def test_the_injected_row_does_not_survive(self, store):
        seed(store)
        check_fault_injection(store, "nba", "2024-25")
        slugs = [r["slug"] for r in store.priced_rows("nba", "2024-25")]
        assert "injected" not in slugs
        assert store.miss_reasons("nba", "2024-25") == {}


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
            "label_agreement", "complementarity", "reconciliation",
            "fault_injection", "shuffled_join"]

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
