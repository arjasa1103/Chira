"""Tests for abbreviation resolution.

The expensive failures here were all silent, so the tests are written against
the specific wrong answers that actually happened:

  - `vgk` instead of `las`, which would have booked 164 real games as
    "no market exists"
  - Utah unresolved in 2025-26 because its schedule nickname is `Mammoth` and
    the market label is `Utah`
  - 0/32 NHL teams for 2024-25 because probing ran in date order
  - accepting a place-level match that could confirm a two-team city's slug
    with the sides SWAPPED
"""

from __future__ import annotations

import json

import pytest

from chira.resolve import (
    candidates,
    confirm,
    invert_learned,
    label_match,
    normalize_nickname,
    prior_lookup,
    probe_order,
    resolve,
    team_labels,
)


def game(gid="g1", **kw):
    base = {"game_id": gid, "et_date": "2025-01-15", "away": "lal", "home": "bos",
            "away_name": "Lakers", "home_name": "Celtics",
            "away_place": "Los Angeles", "home_place": "Boston"}
    return {**base, **kw}


class FakeClient:
    def __init__(self, events=None):
        self.events = events or {}
        self.tried: list[str] = []

    def event_by_slug(self, slug, *, bypass_cache=False):
        self.tried.append(slug)
        return self.events.get(slug, [])


def event(away="Lakers", home="Celtics"):
    return [{"markets": [{"outcomes": json.dumps([away, home])}]}]


class TestNormalization:
    @pytest.mark.parametrize("raw,want", [
        ("Maple Leafs", "mapleleafs"), ("Utah Hockey Club", "utahhockeyclub"),
        ("76ers", "76ers"), ("Montréal", "montral"), ("", ""), (None, ""),
    ])
    def test_normalization(self, raw, want):
        assert normalize_nickname(raw) == want


class TestLabelMatch:
    def test_exact_nickname_matches(self):
        assert label_match(("Kings",), "Kings")

    def test_the_market_label_may_be_shorter_than_the_schedule_label(self):
        """Utah: schedule says 'Utah Hockey Club', the market says 'Utah'."""
        assert label_match(("Utah Hockey Club",), "Utah")

    def test_the_place_label_matches_when_the_nickname_does_not(self):
        """Utah 2025-26: schedule nickname is 'Mammoth', market label is 'Utah'."""
        assert label_match(("Mammoth", "Utah"), "Utah")

    def test_a_different_franchise_does_not_match(self):
        assert not label_match(("Kings",), "Sharks")

    @pytest.mark.parametrize("labels,market", [((), "Kings"), (("",), "Kings"),
                                               (("Kings",), ""), (("Kings",), None)])
    def test_empty_never_matches(self, labels, market):
        assert not label_match(labels, market)


class TestTeamLabels:
    def test_a_unique_place_is_included(self):
        labels = team_labels([game()])
        assert labels["bos"] == ("Celtics", "Boston")

    def test_a_shared_place_is_dropped_from_both_teams(self):
        """'Los Angeles' covers LAL and LAC.

        Accepting a place-level match there lets the resolver confirm a
        Lakers/Clippers slug with the sides swapped, which does not crash: it
        mirrors the calibration curve about 0.5 and looks like a finding.
        """
        games = [game("g1"),
                 game("g2", away="lac", away_name="Clippers",
                      away_place="Los Angeles")]
        labels = team_labels(games)
        assert labels["lal"] == ("Lakers",)
        assert labels["lac"] == ("Clippers",)
        assert labels["bos"] == ("Celtics", "Boston")


class TestPriors:
    def test_invert_learned_picks_up_a_nickname(self):
        learned = {"2024-25": {"sports": {"nhl": {"las": "Golden Knights"}}}}
        assert invert_learned(learned, "nhl", "2024-25") == {"goldenknights": "las"}

    def test_an_ambiguous_prior_is_dropped_rather_than_guessed(self):
        learned = {"2024-25": {"sports": {"nhl": {"a": "Kings", "b": "Kings"}}}}
        assert invert_learned(learned, "nhl", "2024-25") == {}

    def test_a_missing_sport_season_gives_an_empty_prior(self):
        assert invert_learned({}, "nhl", "2024-25") == {}

    def test_prior_lookup_is_loose_enough_for_mammoth(self):
        """Exact key lookup missed this and cost a whole team."""
        assert prior_lookup({"utah": "utah"}, ("Mammoth", "Utah")) == "utah"

    def test_prior_lookup_prefers_the_longest_match(self):
        prior = {"kings": "sac", "sacramentokings": "sack"}
        assert prior_lookup(prior, ("Sacramento Kings",)) == "sack"

    def test_prior_lookup_returns_none_when_nothing_matches(self):
        assert prior_lookup({"kings": "sac"}, ("Sharks",)) is None


class TestCandidates:
    def test_the_prior_comes_before_the_identity_guess(self):
        assert candidates("sjs", ("Sharks",), [{"sharks": "sj"}])[:2] == ["sj", "sjs"]

    def test_the_identity_guess_is_always_present(self):
        assert "lal" in candidates("lal", ("Lakers",), [{}])

    def test_shortened_forms_come_last(self):
        cands = candidates("uta", ("Mammoth", "Utah"), [{}])
        assert cands[0] == "uta"
        assert "utah" in cands, "the bare place name has to be reachable"

    def test_there_are_no_duplicates(self):
        cands = candidates("utah", ("Utah",), [{"utah": "utah"}])
        assert len(cands) == len(set(cands))


class TestProbeOrder:
    def test_mid_season_comes_first(self):
        """Date order resolved 0/32 NHL teams: no early-season coverage."""
        games = [game("early", et_date="2024-10-05"),
                 game("mid", et_date="2025-01-15"),
                 game("late", et_date="2025-04-10")]
        assert next(g["game_id"] for g in probe_order(games)) == "mid"

    def test_it_is_deterministic(self):
        games = [game(f"g{i}", et_date=f"2025-01-{i + 1:02d}") for i in range(9)]
        assert probe_order(games) == probe_order(games)

    def test_it_keeps_every_game(self):
        games = [game(f"g{i}", et_date=f"2025-01-{i + 1:02d}") for i in range(9)]
        assert len(probe_order(games)) == 9

    def test_an_empty_schedule_is_not_an_error(self):
        assert probe_order([]) == []


class TestConfirm:
    def test_a_confirmed_hit_reports_the_slug_and_convention(self):
        client = FakeClient({"nba-lal-bos-2025-01-15": event()})
        hit = confirm(client, "nba", game(), "lal", "bos", team_labels([game()]))
        assert hit["slug"] == "nba-lal-bos-2025-01-15"
        assert hit["convention"] == "et"
        assert hit["market"] is not None

    def test_a_miss_still_reports_every_slug_attempted(self):
        """This is what makes "no market" distinguishable from "never tried"."""
        hit = confirm(FakeClient(), "nba", game(), "lal", "bos", team_labels([game()]))
        assert hit["market"] is None
        assert hit["attempted"] == ["nba-lal-bos-2025-01-15", "nba-lal-bos-2025-01-16"]

    def test_a_swapped_market_is_rejected(self):
        """Away and home reversed in `outcomes` must not confirm."""
        client = FakeClient({"nba-lal-bos-2025-01-15": event("Celtics", "Lakers")})
        hit = confirm(client, "nba", game(), "lal", "bos", team_labels([game()]))
        assert hit["market"] is None

    def test_a_non_moneyline_market_in_the_event_is_skipped(self):
        events = {"nba-lal-bos-2025-01-15": [{"markets": [
            {"outcomes": json.dumps(["Over", "Under"])},
            {"outcomes": json.dumps(["Lakers", "Celtics"])},
        ]}]}
        hit = confirm(FakeClient(events), "nba", game(), "lal", "bos",
                      team_labels([game()]))
        assert hit["market"] is not None

    def test_unparseable_outcomes_do_not_raise(self):
        events = {"nba-lal-bos-2025-01-15": [{"markets": [
            {"outcomes": "not json"}, {"outcomes": ["only one"]}, {}]}]}
        hit = confirm(FakeClient(events), "nba", game(), "lal", "bos",
                      team_labels([game()]))
        assert hit["market"] is None

    def test_bypass_cache_is_forwarded(self):
        class Spy(FakeClient):
            def __init__(self):
                super().__init__()
                self.bypass = []

            def event_by_slug(self, slug, *, bypass_cache=False):
                self.bypass.append(bypass_cache)
                return []

        spy = Spy()
        confirm(spy, "nba", game(), "lal", "bos", team_labels([game()]),
                bypass_cache=True)
        assert all(spy.bypass)


class TestResolve:
    def test_one_hit_resolves_both_sides(self):
        client = FakeClient({"nba-lal-bos-2025-01-15": event()})
        out = resolve(client, "nba", [game()], [{}])
        assert out["map"] == {"lal": "lal", "bos": "bos"}
        assert out["unresolved"] == []
        assert out["probes"] == 1

    def test_pass_two_resolves_a_team_against_a_confirmed_opponent(self):
        """The `vgk -> las` shape: one side irregular, the other already known."""
        games = [game("g1", et_date="2025-01-15"),
                 game("g2", et_date="2025-01-17", away="vgk",
                      away_name="Golden Knights", away_place="Vegas")]
        client = FakeClient({
            "nba-lal-bos-2025-01-15": event(),
            "nba-las-bos-2025-01-17": event("Golden Knights", "Celtics"),
        })
        out = resolve(client, "nba", games, [{"goldenknights": "las"}])
        assert out["map"]["vgk"] == "las"
        assert out["unresolved"] == []

    def test_an_unresolvable_team_is_reported_not_guessed(self):
        client = FakeClient({"nba-lal-bos-2025-01-15": event()})
        games = [game("g1"), game("g2", et_date="2025-01-17", away="xxx",
                                   away_name="Nobody", away_place="Nowhere")]
        out = resolve(client, "nba", games, [{}])
        assert out["unresolved"] == ["xxx"]

    def test_evidence_records_which_slug_proved_each_team(self):
        client = FakeClient({"nba-lal-bos-2025-01-15": event()})
        out = resolve(client, "nba", [game()], [{}])
        assert out["evidence"]["lal"]["slug"] == "nba-lal-bos-2025-01-15"
        assert out["evidence"]["lal"]["convention"] == "et"

    def test_the_probe_budget_is_bounded(self):
        """Without a budget this walks all 1,312 games for one bad team."""
        games = [game(f"g{i}", et_date=f"2025-01-{(i % 28) + 1:02d}")
                 for i in range(200)]
        out = resolve(FakeClient(), "nba", games, [{}], max_probes_per_team=2)
        assert out["probes"] <= 8, out["probes"]
        assert out["unresolved"] == ["bos", "lal"]
