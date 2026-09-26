"""The upcoming-games schedule source the collector runs on.

Offline. The payload shapes here are the ones the real endpoint returned on
2026-09-26, including the detail that makes this module necessary: individual
game objects carry `gameDate: null`, so the ET date has to come from the
enclosing day.
"""

from __future__ import annotations

from datetime import date

import pytest

from chira.http import SchemaError
from chira.upcoming import (
    check_season_window,
    nhl_upcoming,
    parse_start,
    season_label,
    validate_week,
)


def game(gid, away, home, start, *, state="FUT", gtype=2, season=20262027):
    return {
        "id": gid, "gameType": gtype, "gameState": state, "gameDate": None,
        "season": season, "startTimeUTC": start, "neutralSite": False,
        "awayTeam": {"abbrev": away.upper(), "commonName": {"default": f"{away} nick"},
                     "placeName": {"default": f"{away} place"}},
        "homeTeam": {"abbrev": home.upper(), "commonName": {"default": f"{home} nick"},
                     "placeName": {"default": f"{home} place"}},
    }


class FakeClient:
    """Answers /schedule/{date} from a {date: [games]} map, one week at a time."""

    def __init__(self, days: dict, week_len: int = 7):
        self.days, self.week_len, self.calls = days, week_len, []

    def get_json(self, url, validator=None, bypass_cache=False, **kw):
        self.calls.append(url)
        start = date.fromisoformat(url.rsplit("/", 1)[1])
        week = []
        for i in range(self.week_len):
            d = (start.toordinal() + i)
            iso = date.fromordinal(d).isoformat()
            week.append({"date": iso, "games": self.days.get(iso, [])})
        payload = {"gameWeek": week}
        if validator:
            validator(payload)
        return payload


class TestTheETDateComesFromTheDayNotTheGame:
    def test_a_late_game_keeps_the_days_date(self):
        """22:00 ET is 02:00Z the next day; the slug must use the ET date."""
        c = FakeClient({"2026-10-01": [game(1, "chi", "uta", "2026-10-02T01:30:00Z")]})
        out = nhl_upcoming(c, date(2026, 10, 1), days=1)
        assert len(out) == 1
        assert out[0]["et_date"] == "2026-10-01"
        assert out[0]["start_time_utc"] == "2026-10-02T01:30:00Z"

    def test_the_game_objects_own_date_field_is_not_used(self):
        """It is null on this endpoint, which is the whole reason for the rule."""
        g = game(1, "phi", "nj", "2026-10-01T23:00:00Z")
        assert g["gameDate"] is None
        c = FakeClient({"2026-10-01": [g]})
        assert nhl_upcoming(c, date(2026, 10, 1), days=1)[0]["et_date"] == "2026-10-01"


class TestSelection:
    def test_only_regular_season_games(self):
        c = FakeClient({"2026-10-01": [game(1, "a", "b", "2026-10-01T23:00:00Z"),
                                       game(2, "c", "d", "2026-10-01T23:00:00Z", gtype=1)]})
        out = nhl_upcoming(c, date(2026, 10, 1), days=1)
        assert [g["game_id"] for g in out] == ["1"]

    def test_only_games_not_yet_played(self):
        """The census wants OFF/FINAL; this wants the complement."""
        c = FakeClient({"2026-10-01": [game(1, "a", "b", "2026-10-01T23:00:00Z"),
                                       game(2, "c", "d", "2026-10-01T23:00:00Z",
                                            state="FINAL")]})
        assert [g["game_id"] for g in nhl_upcoming(c, date(2026, 10, 1), days=1)] == ["1"]

    def test_days_outside_the_range_are_dropped(self):
        c = FakeClient({"2026-10-01": [game(1, "a", "b", "2026-10-01T23:00:00Z")],
                        "2026-10-05": [game(2, "c", "d", "2026-10-05T23:00:00Z")]})
        out = nhl_upcoming(c, date(2026, 10, 1), days=2)
        assert [g["game_id"] for g in out] == ["1"]

    def test_results_are_sorted_and_deduped(self):
        c = FakeClient({"2026-10-02": [game(9, "a", "b", "2026-10-02T23:00:00Z")],
                        "2026-10-01": [game(2, "c", "d", "2026-10-01T23:00:00Z"),
                                       game(1, "e", "f", "2026-10-01T23:00:00Z")]})
        out = nhl_upcoming(c, date(2026, 10, 1), days=3)
        assert [g["game_id"] for g in out] == ["1", "2", "9"]

    def test_one_request_covers_a_week(self):
        """The endpoint answers with a whole week; asking per day would be 7x."""
        c = FakeClient({"2026-10-01": [game(1, "a", "b", "2026-10-01T23:00:00Z")]})
        nhl_upcoming(c, date(2026, 10, 1), days=7)
        assert len(c.calls) == 1

    def test_zero_days_is_refused(self):
        with pytest.raises(ValueError):
            nhl_upcoming(FakeClient({}), date(2026, 10, 1), days=0)


class TestStrictness:
    def test_a_team_with_no_abbrev_raises(self):
        """Otherwise every slug becomes nhl--bos-<date> and books a false miss."""
        g = game(1, "a", "b", "2026-10-01T23:00:00Z")
        g["awayTeam"]["abbrev"] = ""
        with pytest.raises(SchemaError, match="no abbrev"):
            nhl_upcoming(FakeClient({"2026-10-01": [g]}), date(2026, 10, 1), days=1)

    def test_season_label_shape(self):
        assert season_label(20262027) == "2026-27"
        with pytest.raises(SchemaError):
            season_label("2026")

    def test_validate_week_rejects_a_wrong_shape(self):
        with pytest.raises(SchemaError):
            validate_week([])
        with pytest.raises(SchemaError):
            validate_week({"gameWeek": [{"games": []}]})

    def test_an_empty_week_is_valid_but_not_cacheable(self):
        """Off-season emptiness is a real answer; caching it blinds the collector."""
        assert validate_week({"gameWeek": []}) is False
        assert validate_week({"gameWeek": [{"date": "2026-10-01", "games": []}]}) is True

    def test_parse_start_refuses_a_naive_timestamp(self):
        assert parse_start("2026-10-01T23:00:00Z") is not None
        assert parse_start("2026-10-01 23:00:00") is None
        assert parse_start(None) is None


class TestTheScheduleIsNeverServedFromCache:
    """A cached week freezes the slate for a whole session.

    The collector attaches a disk cache and refreshes targets every 30 minutes.
    Without the bypass that refresh re-reads its own first answer, so a moved or
    newly listed game stays invisible, and `poll_target` pins `game_start_time`
    and `secs_to_tipoff` to whenever the session first looked -- against a column
    documented "re-read every poll, never cached".
    """

    class Recorder(FakeClient):
        def __init__(self, days):
            super().__init__(days)
            self.bypasses = []

        def get_json(self, url, validator=None, bypass_cache=False, **kw):
            self.bypasses.append(bypass_cache)
            return super().get_json(url, validator=validator,
                                    bypass_cache=bypass_cache, **kw)

    def test_enumeration_bypasses_the_cache_by_default(self):
        c = self.Recorder({"2026-10-01": [game(1, "fla", "car",
                                               "2026-10-01T23:00:00Z")]})
        nhl_upcoming(c, date(2026, 10, 1), days=1)
        assert c.bypasses == [True]

    def test_the_bypass_can_be_turned_off_explicitly(self):
        c = self.Recorder({"2026-10-01": []})
        nhl_upcoming(c, date(2026, 10, 1), days=1, bypass_cache=False)
        assert c.bypasses == [False]


class TestSeasonWindowCheck:
    def test_it_refuses_a_sport_it_cannot_actually_scan(self):
        """It scans the NHL schedule, so an NBA window would be checked against
        the wrong league and come back confidently wrong."""
        c = FakeClient({})
        with pytest.raises(ValueError, match="NHL schedule"):
            check_season_window(c, date(2026, 10, 1),
                                (date(2026, 10, 15), date(2027, 4, 20)),
                                sport="nba")


    def test_it_catches_a_window_that_opens_after_the_first_game(self):
        """The real bug: the NHL window said Oct 1, the season opened Sep 29."""
        c = FakeClient({"2026-09-29": [game(1, "fla", "car", "2026-09-29T21:00:00Z")]})
        got = check_season_window(c, date(2026, 9, 20),
                                  (date(2026, 10, 1), date(2027, 4, 30)))
        assert got["first_game"] == "2026-09-29"
        assert got["covered"] is False

    def test_a_correct_window_passes(self):
        c = FakeClient({"2026-09-29": [game(1, "fla", "car", "2026-09-29T21:00:00Z")]})
        got = check_season_window(c, date(2026, 9, 20),
                                  (date(2026, 9, 20), date(2027, 4, 30)))
        assert got["covered"] is True
        assert got["games_found"] == 1
