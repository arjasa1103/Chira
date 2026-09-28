"""The vendored venue table and the distance function.

Offline and data-free by construction: the table is Python literals, which is
the point of vendoring it. The distances below are pinned against published
great-circle figures so a fat-fingered coordinate fails here rather than
becoming a travel coefficient in week 8.
"""

from __future__ import annotations

from collections import Counter

import pytest

from chira.nhl import NHL_TEAMS
from chira.venues import (
    EXPECTED_TEAMS,
    NBA_NEUTRAL_SITES,
    NBA_RELOCATED_HOME,
    NBA_VENUES,
    NHL_VENUES,
    VENUES,
    distance_km,
    haversine_km,
    is_neutral_site,
    neutral_site_rows,
    tz_shift_hours,
    venue,
    venue_rows,
)


class TestTheTableIsComplete:
    def test_every_league_has_the_expected_team_count(self):
        """A short table does not fail, it returns no travel for the teams it
        dropped, which reads as 'this team never travels'."""
        for sport, n in EXPECTED_TEAMS.items():
            assert len(VENUES[sport]) == n, sport

    def test_the_nhl_table_covers_the_censuss_own_team_list(self):
        assert {t.lower() for t in NHL_TEAMS} == set(NHL_VENUES)

    def test_codes_are_lowercase_three_letters_like_the_store(self):
        for sport, table in VENUES.items():
            for team in table:
                assert team == team.lower() and len(team) == 3, (sport, team)

    def test_coordinates_are_on_earth_and_in_north_america(self):
        for sport, table in VENUES.items():
            for team, (lat, lon, city, tz) in table.items():
                assert 25 <= lat <= 55, (sport, team, lat)
                assert -125 <= lon <= -70, (sport, team, lon)
                assert city and -8 <= tz <= -5, (sport, team, city, tz)

    def test_venue_rows_is_flat_and_sorted(self):
        rows = venue_rows()
        assert len(rows) == sum(EXPECTED_TEAMS.values())
        assert rows == sorted(rows, key=lambda r: (r["sport"], r["team"]))

    def test_a_missing_team_raises_rather_than_returning_none(self):
        with pytest.raises(KeyError, match="no venue for nba team"):
            venue("nba", "sea")
        with pytest.raises(KeyError, match="no venue table"):
            venue("mlb", "nyy")


# (sport, a, b, published great-circle km). Tolerance is 2%, which is far
# wider than the ~1 km that two decimal places costs and far tighter than any
# plausible wrong-city error.
PAIRS = [
    ("nba", "bos", "nyk", 306),
    ("nba", "nyk", "lal", 3936),
    ("nba", "mia", "por", 4352),
    ("nba", "chi", "dal", 1290),
    ("nhl", "van", "edm", 817),
    ("nhl", "cgy", "edm", 280),
    ("nhl", "tor", "mtl", 504),
    ("nhl", "sea", "fla", 4357),
    ("nhl", "nyr", "njd", 15),
    ("nhl", "sjs", "lak", 492),
]


class TestDistances:
    @pytest.mark.parametrize("sport,a,b,expected", PAIRS)
    def test_pinned_against_published_distances(self, sport, a, b, expected):
        got = distance_km(sport, a, b)
        assert abs(got - expected) <= max(2.0, 0.02 * expected), (got, expected)

    def test_a_team_is_zero_from_itself(self):
        assert haversine_km(40.0, -80.0, 40.0, -80.0) == 0.0

    def test_distance_is_symmetric(self):
        assert distance_km("nhl", "van", "tbl") == distance_km("nhl", "tbl", "van")

    def test_the_two_la_arenas_are_close_but_not_identical(self):
        """lac moved to Intuit Dome in 2024-25; lal is 9 km away."""
        d = distance_km("nba", "lac", "lal")
        assert 5 < d < 15


class TestTimeZones:
    def test_east_to_west_is_negative(self):
        assert tz_shift_hours("nba", "bos", "lal") == -3
        assert tz_shift_hours("nba", "lal", "bos") == 3

    def test_phoenix_carries_its_standard_offset_not_its_summer_one(self):
        """Arizona does not observe DST; the table stores STANDARD offsets."""
        assert NBA_VENUES["phx"][3] == -7


class TestTheNbaNeutralSiteList:
    """`schedule.nba_games` has no venue field, so this table is the only
    thing standing between the model and a Paris game scored as a home game.
    """

    def test_counts_per_season(self):
        by_season = Counter(season for season, _ in NBA_NEUTRAL_SITES)
        assert dict(by_season) == {"2023-24": 4, "2024-25": 5, "2025-26": 5}

    def test_2023_24_is_present_even_though_the_league_flag_says_otherwise(self):
        """Measured 2026-09-28: all four of that season's neutral games carry
        `isNeutral: false` upstream, while the same fixtures in the two later
        seasons carry true. They are here because `arenaCity` disagreed with
        the home team's city, which does not depend on the flag."""
        assert len([1 for season, _ in NBA_NEUTRAL_SITES if season == "2023-24"]) == 4

    def test_relocated_home_games_are_not_neutral(self):
        """The Spurs at the Moody Center are 120 km from home in front of
        their own crowd. Zeroing the home advantage would be the worse error."""
        assert len(NBA_RELOCATED_HOME) == 6
        assert not set(NBA_NEUTRAL_SITES) & set(NBA_RELOCATED_HOME)
        for season, game_id in NBA_RELOCATED_HOME:
            assert is_neutral_site("nba", season, game_id) is False

    def test_is_neutral_site(self):
        assert is_neutral_site("nba", "2024-25", "0022400621") is True   # Paris
        assert is_neutral_site("nba", "2024-25", "0022400795") is False  # Austin
        assert is_neutral_site("nba", "2024-25", "0022400601") is False  # ordinary
        assert is_neutral_site("nba", "1999-00", "0022400621") is False  # season keyed

    def test_the_nhl_is_not_covered_here(self):
        """The NHL's own flag is in the store and is correct; ORing the two is
        the caller's job, and a stray NHL row here would double-count."""
        assert not [1 for r in neutral_site_rows() if r["sport"] != "nba"]
        assert is_neutral_site("nhl", "2024-25", "2024020001") is False

    def test_every_row_names_known_teams_and_a_real_game_id(self):
        for table in (NBA_NEUTRAL_SITES, NBA_RELOCATED_HOME):
            for (season, game_id), (et_date, away, home, place, why) in table.items():
                assert len(game_id) == 10 and game_id.startswith("002"), game_id
                assert game_id.isdigit(), game_id
                assert away in NBA_VENUES and home in NBA_VENUES, (away, home)
                assert away != home
                assert et_date.startswith(season[:4]) or et_date.startswith(
                    str(int(season[:4]) + 1)), (season, et_date)
                assert place and "," in place
                assert why or table is NBA_RELOCATED_HOME

    def test_rows_are_flat_and_sorted(self):
        rows = neutral_site_rows()
        assert len(rows) == len(NBA_NEUTRAL_SITES)
        assert rows == sorted(rows, key=lambda r: (r["season"], r["game_id"]))
