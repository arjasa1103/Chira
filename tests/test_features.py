"""Point-in-time feature assembly, and the leakage canary that guards it.

PLAN.md Phase 3 pre-registers the canary in these words: *"a query with
`as_of=T` returns byte-identical results against a DB truncated at T and a DB
holding all later rows."* `TestTheLeakageCanary` is that test. It is the
seventh designated P1 test and the only one that can fail silently in
production, because a leak does not raise -- it just makes the model look
good.

Offline: an in-memory `games` table shaped like the snapshot's view, including
`start_time_utc` as ISO text with an explicit offset, which is how the
snapshot stores it.
"""

from __future__ import annotations

import datetime as dt

import duckdb
import pytest

from chira.features import (
    RESULT_DELAY_SECONDS,
    assemble,
    assemble_backtest,
    attach_venues,
    to_unix,
)
from chira.venues import distance_km

DAY = 86400
T0 = 1_735_689_600   # 2025-01-01T00:00:00Z, a round epoch


def iso(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.UTC).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00")


def et_date(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.UTC).date().isoformat()


def game(gid, start, away, home, winner="home", *, sport="nba",
         season="2024-25", neutral=False):
    return (sport, season, str(gid), et_date(start), away, home, winner,
            neutral, iso(start))


def build(games):
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='UTC'")
    con.execute("""CREATE TABLE games (sport VARCHAR, season VARCHAR,
                   game_id VARCHAR, et_date DATE, away VARCHAR, home VARCHAR,
                   winner VARCHAR, neutral_site BOOLEAN,
                   start_time_utc VARCHAR)""")
    if games:
        con.executemany("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?)", games)
    attach_venues(con)
    return con


def target(gid, start, away, home, *, sport="nba", season="2024-25",
           neutral=False):
    return {"sport": sport, "season": season, "game_id": str(gid),
            "et_date": et_date(start), "away": away, "home": home,
            "neutral_site": neutral}


# A three-game history plus a target, all in real cities so travel resolves.
#   G1  Jan 1  bos @ nyk   nyk wins
#   G2  Jan 2  nyk @ bos   nyk wins (back-to-back for both)
#   G3  Jan 5  bos @ lal   the target
HISTORY = [
    game(1, T0, "bos", "nyk", winner="home"),
    game(2, T0 + DAY, "nyk", "bos", winner="away"),
]
TARGET_START = T0 + 4 * DAY
TARGET = target(3, TARGET_START, "bos", "lal")


class TestTheLeakageCanary:
    """The pre-registered regression test, in three escalating forms."""

    def test_truncating_the_store_at_as_of_changes_nothing(self):
        as_of = T0 + 3 * DAY
        full = build([*HISTORY, game(3, TARGET_START, "bos", "lal")])
        truncated = build(HISTORY)   # the target's own row removed as well
        assert assemble(full, [TARGET], as_of=as_of) == \
               assemble(truncated, [TARGET], as_of=as_of)

    def test_a_game_between_as_of_and_tipoff_is_invisible(self):
        """The sharper form. A game that the store HOLDS, that happens after
        as_of and before the target, must not move a single feature."""
        as_of = T0 + 3 * DAY
        later = game(9, T0 + int(3.5 * DAY), "bos", "phi", winner="away")
        without = build([*HISTORY, game(3, TARGET_START, "bos", "lal")])
        with_later = build([*HISTORY, later,
                            game(3, TARGET_START, "bos", "lal")])
        assert assemble(with_later, [TARGET], as_of=as_of) == \
               assemble(without, [TARGET], as_of=as_of)

    def test_the_canary_can_actually_fail(self):
        """A canary that cannot die is decoration. Move as_of past the extra
        game and the SAME comparison must now differ, which proves the two
        stores were distinguishable all along."""
        later = game(9, T0 + int(3.5 * DAY), "bos", "phi", winner="away")
        without = build([*HISTORY, game(3, TARGET_START, "bos", "lal")])
        with_later = build([*HISTORY, later,
                            game(3, TARGET_START, "bos", "lal")])
        as_of = TARGET_START
        assert assemble(with_later, [TARGET], as_of=as_of) != \
               assemble(without, [TARGET], as_of=as_of)

    def test_a_result_after_as_of_does_not_change_a_win_rate(self):
        as_of = T0 + 3 * DAY
        flipped = [HISTORY[0],
                   game(2, T0 + DAY, "nyk", "bos", winner="away"),
                   game(9, T0 + int(3.5 * DAY), "bos", "phi", winner="home")]
        base = build([*HISTORY, game(3, TARGET_START, "bos", "lal")])
        extra = build([*flipped, game(3, TARGET_START, "bos", "lal")])
        a = assemble(base, [TARGET], as_of=as_of)[0]
        b = assemble(extra, [TARGET], as_of=as_of)[0]
        assert a["away_win_rate"] == b["away_win_rate"] == 0.0


class TestAsOfIsMandatory:
    def test_it_has_no_default(self):
        con = build(HISTORY)
        with pytest.raises(TypeError):
            assemble(con, [TARGET])          # no as_of at all

    @pytest.mark.parametrize("bad", [None, "2025-01-01", 1.5, True])
    def test_it_refuses_anything_that_is_not_unix_seconds(self, bad):
        con = build(HISTORY)
        with pytest.raises(TypeError, match="as_of"):
            assemble(con, [TARGET], as_of=bad)

    def test_a_naive_datetime_is_refused(self):
        con = build(HISTORY)
        with pytest.raises(ValueError, match="timezone-aware"):
            assemble(con, [TARGET], as_of=dt.datetime(2025, 1, 3))

    def test_an_aware_datetime_is_accepted_and_equals_its_epoch(self):
        con = build(HISTORY)
        when = dt.datetime.fromtimestamp(T0 + 3 * DAY, dt.UTC)
        assert to_unix(when) == T0 + 3 * DAY
        assert assemble(con, [TARGET], as_of=when) == \
               assemble(con, [TARGET], as_of=T0 + 3 * DAY)

    def test_a_target_that_has_already_started_is_refused(self):
        """Otherwise a game becomes its own previous game."""
        con = build([*HISTORY, game(3, TARGET_START, "bos", "lal")])
        with pytest.raises(ValueError, match="already started"):
            assemble(con, [TARGET], as_of=TARGET_START + 1)

    def test_at_the_opening_whistle_exactly_is_allowed(self):
        con = build([*HISTORY, game(3, TARGET_START, "bos", "lal")])
        rows = assemble(con, [TARGET], as_of=TARGET_START)
        assert rows[0]["away_prior_games"] == 2

    def test_an_empty_target_list_returns_nothing_rather_than_everything(self):
        assert assemble(build(HISTORY), [], as_of=T0) == []


class TestScheduleFeatures:
    def setup_method(self):
        self.con = build([*HISTORY, game(3, TARGET_START, "bos", "lal")])
        self.row = assemble(self.con, [TARGET], as_of=TARGET_START)[0]

    def test_rest_days_count_calendar_days_since_the_previous_game(self):
        assert self.row["away_rest_days"] == 3      # bos last played Jan 2
        assert self.row["home_rest_days"] is None   # lal has not played

    def test_a_back_to_back_is_exactly_one_day(self):
        row = assemble(build(HISTORY), [target(2, T0 + DAY, "nyk", "bos")],
                       as_of=T0 + DAY)[0]
        assert row["away_b2b"] is True and row["home_b2b"] is True
        assert row["away_rest_days"] == 1

    def test_a_team_with_no_prior_game_is_flagged_not_zeroed(self):
        assert self.row["home_first_of_season"] is True
        assert self.row["home_prior_games"] == 0
        assert self.row["home_win_rate"] is None

    def test_games_in_the_last_seven_days(self):
        assert self.row["away_games_7d"] == 2
        assert self.row["home_games_7d"] == 0

    def test_rest_diff_is_home_minus_away(self):
        row = assemble(build(HISTORY), [target(2, T0 + DAY, "nyk", "bos")],
                       as_of=T0 + DAY)[0]
        assert row["rest_diff"] == 0


class TestTravel:
    def test_distance_matches_the_python_haversine(self):
        """Two implementations of one formula. If they can disagree, they
        will, and the SQL one is the one the model would silently use."""
        row = assemble(build(HISTORY), [target(2, T0 + DAY, "nyk", "bos")],
                       as_of=T0 + DAY)[0]
        assert row["away_travel_km"] == pytest.approx(
            distance_km("nba", "nyk", "bos"), rel=1e-12)

    def test_a_team_coming_home_travels_from_where_it_last_played(self):
        row = assemble(build(HISTORY), [target(2, T0 + DAY, "nyk", "bos")],
                       as_of=T0 + DAY)[0]
        # bos played AT nyk, so bos travels nyk -> bos, the same leg.
        assert row["home_travel_km"] == pytest.approx(
            distance_km("nba", "nyk", "bos"))

    def test_a_neutral_site_game_has_no_known_venue(self):
        """The venue is not the home team's city, and guessing it would be
        wrong for exactly the games where travel is most interesting."""
        hist = [game(1, T0, "bos", "nyk", neutral=True)]
        row = assemble(build(hist),
                       [target(2, T0 + DAY, "bos", "lal")],
                       as_of=T0 + DAY)[0]
        assert row["away_travel_km"] is None
        assert row["away_travel_known"] is False
        assert row["away_rest_days"] == 1   # rest is still known

    def test_a_neutral_target_also_has_no_known_venue(self):
        row = assemble(build(HISTORY),
                       [target(3, TARGET_START, "bos", "lal", neutral=True)],
                       as_of=TARGET_START)[0]
        assert row["away_travel_km"] is None and row["away_travel_known"] is False

    def test_the_time_zone_shift_is_signed_east_to_west_negative(self):
        row = assemble(build(HISTORY), [TARGET], as_of=TARGET_START)[0]
        assert row["away_tz_shift"] == -3.0   # bos -> lal


class TestResultAvailability:
    """E9's availability_delay: a result is public at start + delay."""

    def test_a_game_still_in_progress_is_counted_but_not_settled(self):
        start = T0
        as_of = T0 + 3600            # one hour in; an NBA game runs 8400 s
        con = build([game(1, start, "bos", "nyk", winner="home")])
        row = assemble(con, [target(2, as_of, "bos", "lal")], as_of=as_of)[0]
        assert row["away_prior_games"] == 1
        assert row["away_prior_settled"] == 0
        assert row["away_win_rate"] is None

    def test_the_same_game_is_settled_once_the_delay_has_passed(self):
        start = T0
        as_of = T0 + RESULT_DELAY_SECONDS["nba"]
        con = build([game(1, start, "bos", "nyk", winner="home")])
        row = assemble(con, [target(2, as_of, "bos", "lal")], as_of=as_of)[0]
        assert row["away_prior_settled"] == 1 and row["away_win_rate"] == 0.0

    def test_the_delay_is_overridable_for_a_sensitivity_run(self):
        as_of = T0 + 3600
        con = build([game(1, T0, "bos", "nyk", winner="home")])
        row = assemble(con, [target(2, as_of, "bos", "lal")], as_of=as_of,
                       result_delay={"nba": 0})[0]
        assert row["away_prior_settled"] == 1

    def test_an_unknown_sport_gets_the_longest_delay_not_zero(self):
        """Defaulting an unconfigured sport to zero would publish every
        result instantly, and silently."""
        as_of = T0 + 3600
        con = build([game(1, T0, "bos", "nyk", winner="home", sport="wnba")])
        row = assemble(con, [target(2, as_of, "bos", "lal", sport="wnba")],
                       as_of=as_of)[0]
        assert row["away_prior_settled"] == 0

    def test_a_negative_delay_is_refused(self):
        con = build(HISTORY)
        with pytest.raises(ValueError, match="non-negative"):
            assemble(con, [TARGET], as_of=TARGET_START,
                     result_delay={"nba": -1})


class TestBacktestIsTheSameQuery:
    def test_every_game_matches_the_scalar_path(self):
        """The two entry points run one statement with a different `as_of`
        source. If they ever diverge, the audited one is not the one that
        trains the model."""
        games = [*HISTORY, game(3, TARGET_START, "bos", "lal"),
                 game(4, T0 + 5 * DAY, "lal", "nyk", winner="away")]
        con = build(games)
        got = assemble_backtest(con)
        assert len(got) == 4
        for row in got:
            start = next(g for g in games if g[2] == row["game_id"])[8]
            at = int(dt.datetime.fromisoformat(start).timestamp())
            one = assemble(build(games),
                           [target(row["game_id"], at, row["away"],
                                   row["home"])], as_of=at)[0]
            assert row == one, row["game_id"]

    def test_a_lead_moves_as_of_earlier(self):
        con = build([*HISTORY, game(3, TARGET_START, "bos", "lal")])
        at_tip = {r["game_id"]: r for r in assemble_backtest(con)}
        # 3 days and an hour before a Jan 5 tipoff lands on Jan 1, after
        # bos's first game and before its second.
        early = {r["game_id"]: r
                 for r in assemble_backtest(con, lead_seconds=3 * DAY + 3600)}
        assert at_tip["3"]["away_prior_games"] == 2
        assert early["3"]["away_prior_games"] == 1

    def test_a_negative_lead_is_refused(self):
        with pytest.raises(ValueError, match="non-negative"):
            assemble_backtest(build(HISTORY), lead_seconds=-1)

    def test_scoping_by_sport_and_season(self):
        con = build([*HISTORY,
                     game(7, T0, "bos", "nyr", sport="nhl", season="2024-25")])
        assert len(assemble_backtest(con, sport="nba")) == 2
        assert len(assemble_backtest(con, sport="nhl")) == 1
        assert assemble_backtest(con, season="1999-00") == []


def test_no_price_column_reaches_the_feature_frame():
    """Headline 1 is a PRICE-FREE model. The cheapest guarantee is that the
    builder has no price column at all; the nested test joins prices itself."""
    con = build([*HISTORY, game(3, TARGET_START, "bos", "lal")])
    cols = set(assemble(con, [TARGET], as_of=TARGET_START)[0])
    assert not {c for c in cols if "price" in c or c.startswith("p_")}
