"""The upcoming-games schedule source the collector runs on.

Offline. The payload shapes here are the ones the real endpoint returned on
2026-09-26, including the detail that makes this module necessary: individual
game objects carry `gameDate: null`, so the ET date has to come from the
enclosing day.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from chira.http import SchemaError
from chira.upcoming import (
    NBA_ALL_STATES,
    check_season_window,
    espn_abbrev,
    nba_season_label,
    nba_upcoming,
    nhl_upcoming,
    parse_start,
    season_label,
    validate_scoreboard,
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
        """A window must never be checked against another league's schedule.

        This used to assert on `sport="nba"`, because the scan was
        `nhl_upcoming` unconditionally and the NBA had no enumerator. The NBA
        is wired now (`TestTheWindowCheckScansTheSportItWasAsked`), so the
        guarantee is pinned on a sport that still has none -- it is the
        guarantee that matters, not the example.
        """
        c = FakeClient({})
        with pytest.raises(ValueError, match="no upcoming-games source"):
            check_season_window(c, date(2026, 10, 1),
                                (date(2026, 10, 15), date(2027, 4, 20)),
                                sport="mlb")


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


# --- NBA, via ESPN -------------------------------------------------------
#
# Payload shapes are the ones site.api.espn.com returned on 2026-10-20, the
# NBA's 2026-27 opening day, including the two details that shape the module:
# a 21:30 ET tipoff arrives under the PREVIOUS day's `dates=` query with a
# next-day UTC timestamp, and BOS@DET was published as 19:00Z / "3:00 PM EDT"
# on a slate whose other two games were 19:00 and 21:30 ET.

def espn_event(gid, away, home, start, *, state="pre", slug="regular-season",
               year=2027, neutral=False):
    def side(code, which):
        names = {"bos": ("Celtics", "Boston"), "det": ("Pistons", "Detroit"),
                 "gs": ("Warriors", "Golden State"),
                 "lal": ("Lakers", "Los Angeles"),
                 "lac": ("Clippers", "LA"), "ny": ("Knicks", "New York"),
                 "no": ("Pelicans", "New Orleans"),
                 "sa": ("Spurs", "San Antonio"), "utah": ("Jazz", "Utah"),
                 "wsh": ("Wizards", "Washington"),
                 "okc": ("Thunder", "Oklahoma City")}
        nick, place = names.get(code, (f"{code} nick", f"{code} place"))
        return {"homeAway": which,
                "team": {"abbreviation": code.upper(), "name": nick,
                         "location": place}}
    return {
        "id": str(gid), "date": start,
        "season": {"year": year, "slug": slug},
        "competitions": [{
            "neutralSite": neutral,
            "status": {"type": {"state": state, "name": "STATUS_SCHEDULED"}},
            "competitors": [side(away, "away"), side(home, "home")],
        }],
    }


class FakeEspn:
    """Answers /scoreboard?dates=YYYYMMDD from a {iso date: [events]} map."""

    def __init__(self, days: dict):
        self.days, self.calls = days, []

    def get_json(self, url, validator=None, bypass_cache=False, **kw):
        self.calls.append(url)
        stamp = url.rsplit("dates=", 1)[1]
        iso = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
        payload = {"events": list(self.days.get(iso, []))}
        if validator:
            validator(payload)
        return payload


NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class TestNbaETDateComesFromTheQueryNotTheTimestamp:
    def test_a_late_tipoff_keeps_the_queried_date(self):
        """21:30 ET in San Antonio is 01:30Z the next day."""
        c = FakeEspn({"2026-10-20": [
            espn_event(1, "okc", "sa", "2026-10-21T01:30Z")]})
        out = nba_upcoming(c, date(2026, 10, 20), days=1, now=NOW)
        assert [g["et_date"] for g in out] == ["2026-10-20"]
        assert out[0]["start_time_utc"] == "2026-10-21T01:30:00Z"

    def test_one_request_per_day(self):
        c = FakeEspn({})
        nba_upcoming(c, date(2026, 10, 20), days=3, now=NOW)
        assert [u.rsplit("=", 1)[1] for u in c.calls] == [
            "20261020", "20261021", "20261022"]

    def test_a_dark_day_is_not_cacheable(self):
        """An empty slate is a real answer; freezing it would blind the run."""
        assert validate_scoreboard({"events": []}) is False
        assert validate_scoreboard({"events": [{"id": "1"}]}) is True
        with pytest.raises(SchemaError):
            validate_scoreboard({"no_events": []})


class TestNbaAbbreviationsBecomeCensusCodes:
    @pytest.mark.parametrize("espn,census", [
        ("gs", "gsw"), ("no", "nop"), ("ny", "nyk"), ("sa", "sas"),
        ("utah", "uta"), ("wsh", "was"), ("bos", "bos"), ("phx", "phx")])
    def test_each_translation(self, espn, census):
        assert espn_abbrev(espn.upper()) == census

    def test_a_blank_code_raises_rather_than_slugging_a_blank_side(self):
        with pytest.raises(SchemaError):
            espn_abbrev("")

    def test_the_two_los_angeles_spellings_are_collapsed(self):
        """`resolve.team_labels` only trusts a place name unique in the league.

        ESPN writes the Clippers' city "LA" and the Lakers' "Los Angeles".
        Two spellings both look unique, which would re-admit place-level
        matching for exactly the pair the guard exists to protect.
        """
        c = FakeEspn({"2026-10-21": [
            espn_event(1, "gs", "lal", "2026-10-22T02:00Z"),
            espn_event(2, "no", "lac", "2026-10-22T02:30Z")]})
        out = nba_upcoming(c, date(2026, 10, 21), days=1, now=NOW)
        places = {g["home"]: g["home_place"] for g in out}
        assert places == {"lal": "Los Angeles", "lac": "Los Angeles"}

        from chira.resolve import team_labels
        labels = team_labels(out)
        assert "Los Angeles" not in labels["lal"]
        assert "Los Angeles" not in labels["lac"]
        assert labels["lal"] == ("Lakers",)


class TestNbaSelection:
    def test_preseason_is_excluded(self):
        """Preseason runs to 10-16 and the NBA window opens 10-15."""
        c = FakeEspn({"2026-10-16": [
            espn_event(1, "bos", "det", "2026-10-16T23:00Z",
                       slug="preseason")]})
        assert nba_upcoming(c, date(2026, 10, 16), days=1, now=NOW) == []

    def test_only_the_requested_states(self):
        c = FakeEspn({"2026-10-20": [
            espn_event(1, "bos", "det", "2026-10-20T23:00Z", state="pre"),
            espn_event(2, "ny", "sa", "2026-10-21T01:30Z", state="post")]})
        pre = nba_upcoming(c, date(2026, 10, 20), days=1, now=NOW)
        assert [g["game_id"] for g in pre] == ["1"]
        every = nba_upcoming(c, date(2026, 10, 20), days=1,
                             states=NBA_ALL_STATES, now=NOW)
        assert [g["game_id"] for g in every] == ["1", "2"]

    def test_season_label_is_the_end_year_minus_one(self):
        assert nba_season_label(2027) == "2026-27"
        assert nba_season_label("2027") == "2026-27"
        for bad in (None, "", "nope", 1800):
            with pytest.raises(SchemaError):
                nba_season_label(bad)

    def test_a_malformed_event_raises_rather_than_guessing_sides(self):
        one = espn_event(1, "bos", "det", "2026-10-20T23:00Z")
        one["competitions"][0]["competitors"].pop()
        with pytest.raises(SchemaError):
            nba_upcoming(FakeEspn({"2026-10-20": [one]}),
                         date(2026, 10, 20), days=1, now=NOW)

        both_home = espn_event(2, "bos", "det", "2026-10-20T23:00Z")
        both_home["competitions"][0]["competitors"][0]["homeAway"] = "home"
        with pytest.raises(SchemaError):
            nba_upcoming(FakeEspn({"2026-10-20": [both_home]}),
                         date(2026, 10, 20), days=1, now=NOW)


class TestNbaDoesNotBelieveAStaleTipoff:
    """ESPN's time is third-party, and a wrong-EARLY one loses the game.

    `collector.upcoming_targets` drops a game 30 minutes past its scheduled
    tipoff, so believing a placeholder 4 hours early would end pre-game
    capture 4 hours early -- and pre-game prices cannot be fetched later.
    """

    EVENT = ("2026-10-20", 1, "bos", "det", "2026-10-20T19:00Z")

    def _run(self, now, state="pre"):
        day, gid, away, home, start = self.EVENT
        c = FakeEspn({day: [espn_event(gid, away, home, start, state=state)]})
        out = nba_upcoming(c, date.fromisoformat(day), days=1,
                           states=NBA_ALL_STATES, now=now)
        return out[0]

    def test_a_future_tipoff_is_kept(self):
        got = self._run(datetime(2026, 10, 20, 18, 0, tzinfo=UTC))
        assert got["start_time_utc"] == "2026-10-20T19:00:00Z"

    def test_inside_the_grace_it_is_still_kept(self):
        got = self._run(datetime(2026, 10, 20, 19, 15, tzinfo=UTC))
        assert got["start_time_utc"] == "2026-10-20T19:00:00Z"

    def test_past_the_grace_and_still_pre_the_time_is_dropped(self):
        got = self._run(datetime(2026, 10, 20, 19, 45, tzinfo=UTC))
        assert got["start_time_utc"] is None
        assert got["game_id"] == "1"

    def test_a_game_that_actually_started_keeps_its_time(self):
        """`in` corroborates the clock with something other than itself."""
        got = self._run(datetime(2026, 10, 20, 23, 0, tzinfo=UTC), state="in")
        assert got["start_time_utc"] == "2026-10-20T19:00:00Z"

    def test_the_dropped_time_makes_the_game_pollable_not_droppable(self):
        """The whole point: unknown-start games are KEPT by the collector."""
        from chira.collector import upcoming_targets
        got = self._run(datetime(2026, 10, 20, 19, 45, tzinfo=UTC))
        kept = upcoming_targets([got],
                                now=datetime(2026, 10, 20, 22, 0, tzinfo=UTC))
        assert [g["game_id"] for g in kept] == ["1"]


class TestTheWindowCheckScansTheSportItWasAsked:
    def test_nba_scans_the_nba_schedule(self):
        c = FakeEspn({"2026-10-20": [
            espn_event(1, "bos", "det", "2026-10-20T23:00Z")]})
        got = check_season_window(c, date(2026, 10, 18),
                                  (date(2026, 10, 15), date(2027, 4, 20)),
                                  scan_days=5, sport="nba")
        assert got["sport"] == "nba"
        assert got["first_game"] == "2026-10-20"
        assert got["covered"] is True

    def test_a_window_that_opens_after_the_opener_is_caught(self):
        c = FakeEspn({"2026-10-20": [
            espn_event(1, "bos", "det", "2026-10-20T23:00Z")]})
        got = check_season_window(c, date(2026, 10, 18),
                                  (date(2026, 10, 25), date(2027, 4, 20)),
                                  scan_days=5, sport="nba")
        assert got["covered"] is False

    def test_an_unwired_sport_still_raises(self):
        """It must never verify a window against another league's schedule."""
        with pytest.raises(ValueError, match="no upcoming-games source"):
            check_season_window(FakeEspn({}), date(2026, 10, 1),
                                (date(2026, 10, 1), date(2027, 4, 1)),
                                sport="mlb")
