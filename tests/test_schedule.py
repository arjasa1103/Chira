"""Tests for schedule folding: orientation, side attribution, and order.

`nba_games` is the E1 ground-truth label source, and the three ways it can be
silently wrong are all in the pure part extracted here:

  - MATCHUP comes in two forms ("LAL @ BOS" and "BOS vs. LAL") and reading the
    second one as away-first swaps every home and away in the census
  - PTS and WL arrive one row PER TEAM, so attributing a row to the wrong side
    loses the score and the game is dropped as if it had no data
  - the rows arrive newest-first, which made `--limit 200` census the LAST 200
    games of the season
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from chira.schedule import attach_start_times, games_from_rows, slug, slug_candidates

NICK = {"lal": "Lakers", "bos": "Celtics", "gsw": "Warriors"}
PLACE = {"lal": "Los Angeles", "bos": "Boston", "gsw": "Golden State"}


def row(gid="0022400001", date="2025-01-15", matchup="LAL @ BOS", abbr="LAL",
        pts=100, wl="L"):
    return SimpleNamespace(GAME_ID=gid, GAME_DATE=date, MATCHUP=matchup,
                           TEAM_ABBREVIATION=abbr, PTS=pts, WL=wl)


def pair(gid="0022400001", date="2025-01-15", away_pts=100, home_pts=110):
    """The two rows nba_api emits for one game, in both MATCHUP forms."""
    away_won = away_pts > home_pts
    return [
        row(gid, date, "LAL @ BOS", "LAL", away_pts, "W" if away_won else "L"),
        row(gid, date, "BOS vs. LAL", "BOS", home_pts, "L" if away_won else "W"),
    ]


class TestOrientation:
    def test_at_form_is_away_first_and_vs_form_is_home_first(self):
        g = games_from_rows(pair(), NICK, PLACE)[0]
        assert (g["away"], g["home"]) == ("lal", "bos")
        assert (g["away_pts"], g["home_pts"]) == (100, 110)

    def test_labels_come_from_the_static_table(self):
        g = games_from_rows(pair(), NICK, PLACE)[0]
        assert (g["away_name"], g["home_name"]) == ("Lakers", "Celtics")
        assert (g["away_place"], g["home_place"]) == ("Los Angeles", "Boston")

    def test_an_unknown_abbreviation_gets_an_empty_label_not_a_wrong_one(self):
        rows = [row(abbr="LAL", matchup="LAL @ BOS", wl="W"),
                row(abbr="BOS", matchup="BOS vs. LAL", pts=90)]
        g = games_from_rows(rows, {"lal": "Lakers"}, {})[0]
        assert g["home_name"] == "" and g["home_place"] == ""

    def test_the_home_winner_case(self):
        assert games_from_rows(pair(away_pts=99, home_pts=101), NICK, PLACE)[0]["winner"] == "home"

    def test_the_away_winner_case(self):
        assert games_from_rows(pair(away_pts=120, home_pts=101), NICK, PLACE)[0]["winner"] == "away"


class TestSideAttribution:
    def test_an_abbreviation_matching_neither_side_raises(self):
        """Defaulting to 'home' wrote both rows into one slot, silently."""
        rows = pair()
        rows[1] = row(matchup="BOS vs. LAL", abbr="GSW", pts=110, wl="W")
        with pytest.raises(ValueError, match="matches neither"):
            games_from_rows(rows, NICK, PLACE)

    def test_a_game_with_only_one_team_row_is_dropped(self):
        assert games_from_rows([pair()[0]], NICK, PLACE) == []

    def test_a_game_with_no_winner_is_dropped(self):
        rows = [row(abbr="LAL", wl="L"), row(matchup="BOS vs. LAL", abbr="BOS", wl="L")]
        assert games_from_rows(rows, NICK, PLACE) == []

    def test_a_null_pts_row_is_dropped_rather_than_scored(self):
        rows = pair()
        rows[0] = row(matchup="LAL @ BOS", abbr="LAL", pts=None, wl="L")
        assert games_from_rows(rows, NICK, PLACE) == []


class TestFilteringAndOrder:
    def test_an_unparseable_matchup_is_skipped(self):
        assert games_from_rows([row(matchup="LAL vs BOS in Paris")], NICK, PLACE) == []

    def test_rows_come_back_oldest_first(self):
        """nba_api returns newest first; unsorted output broke --limit."""
        rows = pair("g2", "2025-03-01") + pair("g1", "2024-11-05")
        dates = [g["et_date"] for g in games_from_rows(rows, NICK, PLACE)]
        assert dates == ["2024-11-05", "2025-03-01"]

    def test_ties_in_date_are_broken_by_game_id(self):
        rows = pair("0022400009", "2025-01-15") + pair("0022400002", "2025-01-15")
        ids = [g["game_id"] for g in games_from_rows(rows, NICK, PLACE)]
        assert ids == ["0022400002", "0022400009"]

    def test_the_et_date_is_truncated_to_ten_characters(self):
        rows = pair(date="2025-01-15T00:00:00")
        assert games_from_rows(rows, NICK, PLACE)[0]["et_date"] == "2025-01-15"

    def test_no_rows_is_not_an_error(self):
        assert games_from_rows([], NICK, PLACE) == []


class TestSlugs:
    def test_both_date_conventions_are_emitted_in_order(self):
        g = games_from_rows(pair(), NICK, PLACE)[0]
        assert slug_candidates("nba", g) == [
            ("et", "nba-lal-bos-2025-01-15"),
            ("et_plus_1", "nba-lal-bos-2025-01-16"),
        ]

    def test_the_abbreviation_map_is_applied_to_both_sides(self):
        g = games_from_rows(pair(), NICK, PLACE)[0]
        got = slug_candidates("nhl", g, {"lal": "las", "bos": "bo"})
        assert got[0][1] == "nhl-las-bo-2025-01-15"

    def test_slug_returns_the_primary_candidate(self):
        g = games_from_rows(pair(), NICK, PLACE)[0]
        assert slug("nba", g) == "nba-lal-bos-2025-01-15"

    def test_the_plus_one_convention_crosses_a_month_boundary(self):
        g = games_from_rows(pair(date="2025-01-31"), NICK, PLACE)[0]
        assert slug_candidates("nba", g)[1][1] == "nba-lal-bos-2025-02-01"


class TestAttachStartTimes:
    def test_the_league_time_is_attached_by_game_id(self):
        games = games_from_rows(pair(), NICK, PLACE)
        got = attach_start_times(games, {"0022400001": "2025-01-16T00:30:00Z"})
        assert got[0]["start_time_utc"] == "2025-01-16T00:30:00Z"

    @pytest.mark.parametrize("value", [None, "", float("nan"), "None"])
    def test_a_missing_time_is_none_so_the_census_falls_back_visibly(self, value):
        games = games_from_rows(pair(), NICK, PLACE)
        league = {} if value is None else {"0022400001": value}
        assert attach_start_times(games, league)[0]["start_time_utc"] is None

    def test_the_input_games_are_not_mutated(self):
        games = games_from_rows(pair(), NICK, PLACE)
        attach_start_times(games, {"0022400001": "2025-01-16T00:30:00Z"})
        assert "start_time_utc" not in games[0]
