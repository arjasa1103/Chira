"""Tests for the NHL schedule source (E10).

The facts asserted here were measured on 2026-09-12 against api-web.nhle.com
(see notes/week2-nhl-schedule.md). The payload shapes are stubbed; what is
being tested is the reading of them, especially the two places where a wrong
reading would be silent: the ET date and the winner.
"""

from __future__ import annotations

import pytest

from chira.nhl import GAMES_PER_SEASON, NHL_TEAMS, nhl_games, season_code


class FakeClient:
    def __init__(self, by_team):
        self.by_team = by_team
        self.calls: list[str] = []

    def get_json(self, url):
        self.calls.append(url)
        team = url.rstrip("/").split("/")[-2]
        return {"games": self.by_team.get(team, [])}


def raw(gid=2024020006, date="2024-10-09", away="TOR", home="MTL",
        away_score=0, home_score=1, state="OFF", gtype=2, **kw):
    g = {
        "id": gid, "gameType": gtype, "gameDate": date, "gameState": state,
        "startTimeUTC": "2024-10-09T23:00:00Z",
        "awayTeam": {"abbrev": away, "commonName": {"default": "Maple Leafs"},
                     "placeName": {"default": "Toronto"}, "score": away_score},
        "homeTeam": {"abbrev": home, "commonName": {"default": "Canadiens"},
                     "placeName": {"default": "Montréal"}, "score": home_score},
    }
    g.update(kw)
    return g


class TestSeasonCode:
    def test_the_two_usable_seasons(self):
        assert season_code("2024-25") == "20242025"
        assert season_code("2025-26") == "20252026"

    @pytest.mark.parametrize("bad", ["2024-2025", "24-25", "2024-26", "2024",
                                     "x", "", "2024-24"])
    def test_anything_else_raises_rather_than_guessing(self, bad):
        with pytest.raises(ValueError, match="2024-25"):
            season_code(bad)


class TestVendoredTeams:
    def test_there_are_thirty_two(self):
        assert len(NHL_TEAMS) == 32
        assert len(set(NHL_TEAMS)) == 32

    def test_utah_is_present(self):
        """Utah entered the league in 2024-25, inside the usable window."""
        assert "UTA" in NHL_TEAMS

    def test_the_measured_season_size_is_recorded(self):
        assert GAMES_PER_SEASON == 1312


class TestReading:
    def test_a_completed_game_becomes_a_row_with_an_independent_winner(self):
        client = FakeClient({"TOR": [raw()]})
        games = nhl_games(client, "2024-25", teams=("TOR",))
        assert len(games) == 1
        g = games[0]
        assert g == {
            "game_id": "2024020006", "et_date": "2024-10-09", "away": "tor",
            "home": "mtl", "away_name": "Maple Leafs", "home_name": "Canadiens",
            "away_place": "Toronto", "home_place": "Montréal",
            "away_pts": 0, "home_pts": 1, "winner": "home", "neutral_site": False,
        }

    def test_the_away_winner_case(self):
        client = FakeClient({"TOR": [raw(away_score=4, home_score=2)]})
        assert nhl_games(client, "2024-25", teams=("TOR",))[0]["winner"] == "away"

    def test_games_are_deduped_across_both_teams(self):
        client = FakeClient({"TOR": [raw()], "MTL": [raw()]})
        assert len(nhl_games(client, "2024-25", teams=("TOR", "MTL"))) == 1

    def test_the_et_date_is_taken_from_gameDate_not_from_startTimeUTC(self):
        """Measured: LAK @ VGK is gameDate 2024-10-22 at 2024-10-23T03:00:00Z."""
        client = FakeClient({"LAK": [raw(date="2024-10-22",
                                        startTimeUTC="2024-10-23T03:00:00Z")]})
        assert nhl_games(client, "2024-25", teams=("LAK",))[0]["et_date"] == "2024-10-22"

    def test_rows_come_back_sorted_by_date(self):
        client = FakeClient({"TOR": [raw(gid=2, date="2025-01-02"),
                                     raw(gid=1, date="2024-12-01")]})
        dates = [g["et_date"] for g in nhl_games(client, "2024-25", teams=("TOR",))]
        assert dates == sorted(dates)

    def test_a_neutral_site_game_is_flagged(self):
        client = FakeClient({"TOR": [raw(neutralSite=True)]})
        assert nhl_games(client, "2024-25", teams=("TOR",))[0]["neutral_site"] is True


class TestFiltering:
    @pytest.mark.parametrize("gtype", [1, 3])
    def test_preseason_and_playoff_games_are_excluded(self, gtype):
        client = FakeClient({"TOR": [raw(gtype=gtype)]})
        assert nhl_games(client, "2024-25", teams=("TOR",)) == []

    @pytest.mark.parametrize("state", ["FUT", "PRE", "LIVE", "CRIT"])
    def test_an_unplayed_game_is_neither_a_row_nor_a_miss(self, state):
        client = FakeClient({"TOR": [raw(state=state)]})
        assert nhl_games(client, "2024-25", teams=("TOR",)) == []

    def test_a_completed_game_with_no_score_is_dropped(self):
        client = FakeClient({"TOR": [raw(away_score=None, home_score=None)]})
        assert nhl_games(client, "2024-25", teams=("TOR",)) == []

    def test_equal_scores_raise_instead_of_guessing_a_winner(self):
        """Zero occurrences across all 2,624 games; a guess would corrupt E1."""
        client = FakeClient({"TOR": [raw(away_score=3, home_score=3)]})
        with pytest.raises(ValueError, match="equal scores"):
            nhl_games(client, "2024-25", teams=("TOR",))


class TestRequestShape:
    def test_one_call_per_team_with_the_season_code(self):
        client = FakeClient({})
        nhl_games(client, "2025-26", teams=("TOR", "MTL"))
        assert len(client.calls) == 2
        assert client.calls[0].endswith("/club-schedule-season/TOR/20252026")
