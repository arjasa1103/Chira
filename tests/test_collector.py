"""The forward collector's gates, keys and failure semantics.

Everything here is offline. The collector's value is almost entirely in the
decisions it makes ABOUT polling — when to poll, when a zero is an outage, what
makes two quotes the same observation — and those are exactly the parts that a
live test would not check anyway.

The DST tests are not decoration. The season and daily windows are Eastern
concepts evaluated on a UTC clock, which is the bug class that already cost this
project a slug convention.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from chira.collector import (
    ET,
    HEARTBEAT_PROVIDERS,
    UTC,
    CollectorStore,
    Heartbeat,
    active_seasons,
    dedup_key,
    describe_plan,
    et_now,
    in_poll_window,
    is_season_active,
    next_poll_delay,
    parse_book,
    quote_row,
    upcoming_targets,
    zero_capture_is_a_failure,
)

WINDOWS = {("nba", "2026-27"): (datetime(2026, 10, 15).date(),
                                datetime(2027, 4, 20).date())}


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=UTC)


class TestTimeZoneGates:
    def test_naive_datetime_is_refused(self):
        """An unlabelled wall clock is how the DST bugs get in."""
        with pytest.raises(ValueError, match="naive"):
            et_now(datetime(2026, 11, 1, 12, 0))

    def test_season_gate_uses_the_ET_date_not_the_UTC_date(self):
        """01:00 UTC on Oct 15 is still Oct 14 in ET, i.e. off-season.

        A UTC-date gate would open the season a day early and, at the other
        end, poll a day after it closed.
        """
        assert not is_season_active(utc(2026, 10, 15, 1, 0), WINDOWS)
        assert is_season_active(utc(2026, 10, 15, 16, 0), WINDOWS)

    def test_off_season_is_inactive(self):
        assert not is_season_active(utc(2026, 7, 4, 18, 0), WINDOWS)
        assert active_seasons(utc(2026, 7, 4, 18, 0), WINDOWS) == []

    def test_active_seasons_names_the_pair(self):
        assert active_seasons(utc(2026, 12, 1, 20, 0), WINDOWS) == [("nba", "2026-27")]

    def test_poll_window_spans_midnight(self):
        """A 22:30 ET tipoff is still quoted at 01:00 ET the NEXT date."""
        assert in_poll_window(datetime(2026, 12, 1, 23, 0, tzinfo=ET))
        assert in_poll_window(datetime(2026, 12, 2, 1, 0, tzinfo=ET))
        assert not in_poll_window(datetime(2026, 12, 1, 12, 0, tzinfo=ET))

    def test_window_edges(self):
        assert in_poll_window(datetime(2026, 12, 1, 16, 0, tzinfo=ET))
        assert in_poll_window(datetime(2026, 12, 2, 2, 30, tzinfo=ET))
        assert not in_poll_window(datetime(2026, 12, 2, 3, 0, tzinfo=ET))

    def test_the_same_utc_hour_falls_differently_across_the_dst_shift(self):
        """20:30 UTC is 16:30 EDT (in window) but 15:30 EST (out of it).

        This is the entire reason the gate is not a UTC cron: a fixed UTC hour
        moves an hour relative to the slate when the offset changes.
        """
        assert in_poll_window(utc(2026, 10, 20, 20, 30))    # EDT, UTC-4
        assert not in_poll_window(utc(2026, 12, 20, 20, 30))  # EST, UTC-5

    def test_describe_plan_reports_the_offset_it_used(self):
        p = describe_plan(utc(2026, 12, 20, 22, 0), WINDOWS)
        assert p["et_offset_hours"] == -5.0
        assert p["season_active"] is True
        p2 = describe_plan(utc(2026, 10, 20, 22, 0), WINDOWS)
        assert p2["et_offset_hours"] == -4.0


class TestDedupKey:
    def test_same_second_is_the_same_observation(self):
        t = utc(2026, 12, 1, 23, 30)
        assert dedup_key("nba", "2026-27", "tok", t) == \
               dedup_key("nba", "2026-27", "tok", t)

    def test_different_seconds_are_different_observations(self):
        t = utc(2026, 12, 1, 23, 30)
        assert dedup_key("nba", "2026-27", "tok", t) != \
               dedup_key("nba", "2026-27", "tok", t + timedelta(seconds=1))

    def test_the_key_is_timezone_invariant(self):
        """The same instant expressed in two zones is ONE observation."""
        t = utc(2026, 12, 1, 23, 30)
        assert dedup_key("nba", "2026-27", "tok", t) == \
               dedup_key("nba", "2026-27", "tok", t.astimezone(ET))

    def test_different_tokens_do_not_collide(self):
        t = utc(2026, 12, 1, 23, 30)
        assert dedup_key("nba", "2026-27", "a", t) != \
               dedup_key("nba", "2026-27", "b", t)

    def test_naive_timestamp_is_refused(self):
        with pytest.raises(ValueError, match="aware"):
            dedup_key("nba", "2026-27", "tok", datetime(2026, 12, 1, 23, 30))


class TestParseBook:
    def test_best_bid_and_ask_are_the_inside_of_the_book(self):
        book = {"bids": [{"price": "0.40"}, {"price": "0.42"}],
                "asks": [{"price": "0.46"}, {"price": "0.44"}]}
        assert parse_book(book) == {"best_bid": 0.42, "best_ask": 0.44,
                                    "spread": pytest.approx(0.02)}

    def test_a_resolved_market_has_no_orderbook(self):
        """`/book` returns "No orderbook exists" once a market settles."""
        assert parse_book("No orderbook exists") == {
            "best_bid": None, "best_ask": None, "spread": None}

    def test_an_empty_book_is_none_not_zero(self):
        """A $0 bid and no bid are different facts."""
        assert parse_book({"bids": [], "asks": []})["best_bid"] is None

    def test_unparseable_prices_do_not_become_zero(self):
        out = parse_book({"bids": [{"price": "abc"}], "asks": [{"price": None}]})
        assert out["best_bid"] is None and out["best_ask"] is None

    def test_one_sided_book_has_no_spread(self):
        out = parse_book({"bids": [{"price": "0.4"}], "asks": []})
        assert out["best_bid"] == 0.4 and out["spread"] is None


class TestQuoteRow:
    def test_capture_time_and_time_to_tipoff_are_recorded(self):
        cap = utc(2026, 12, 1, 23, 30)
        row = quote_row(sport="nba", season="2026-27", game_id="1", slug="s",
                        token_id="tok", side="home", captured_at=cap,
                        midpoint={"mid": "0.55"}, book={"bids": [], "asks": []},
                        game_start_time=cap + timedelta(minutes=30),
                        poll_seq=1, run_id="r")
        assert row["midpoint"] == 0.55
        assert row["secs_to_tipoff"] == 1800
        assert row["captured_at"] == cap

    def test_an_unknown_tipoff_is_none_not_a_guess(self):
        row = quote_row(sport="nba", season="2026-27", game_id="1", slug=None,
                        token_id="tok", side="home", captured_at=utc(2026, 12, 1),
                        midpoint=None, book=None, game_start_time=None,
                        poll_seq=1, run_id="r")
        assert row["secs_to_tipoff"] is None and row["midpoint"] is None

    def test_a_post_tipoff_capture_has_a_negative_countdown(self):
        cap = utc(2026, 12, 1, 23, 30)
        row = quote_row(sport="nba", season="2026-27", game_id="1", slug="s",
                        token_id="tok", side="home", captured_at=cap,
                        midpoint={"mid": "0.5"}, book=None,
                        game_start_time=cap - timedelta(minutes=10),
                        poll_seq=1, run_id="r")
        assert row["secs_to_tipoff"] == -600


class TestStore:
    def test_a_repoll_of_the_same_second_replaces_rather_than_duplicates(self, tmp_path):
        cap = utc(2026, 12, 1, 23, 30)
        row = quote_row(sport="nba", season="2026-27", game_id="1", slug="s",
                        token_id="tok", side="home", captured_at=cap,
                        midpoint={"mid": "0.55"}, book=None, game_start_time=None,
                        poll_seq=1, run_id="r")
        with CollectorStore(tmp_path / "live.duckdb") as s:
            s.put_quotes([row])
            s.put_quotes([row])
            assert s.quote_count() == 1

    def test_distinct_seconds_both_persist(self, tmp_path):
        cap = utc(2026, 12, 1, 23, 30)
        rows = [quote_row(sport="nba", season="2026-27", game_id="1", slug="s",
                          token_id="tok", side="home",
                          captured_at=cap + timedelta(seconds=i),
                          midpoint={"mid": "0.55"}, book=None,
                          game_start_time=None, poll_seq=i, run_id="r")
                for i in range(3)]
        with CollectorStore(tmp_path / "live.duckdb") as s:
            s.put_quotes(rows)
            assert s.quote_count() == 3

    def test_empty_put_is_a_noop(self, tmp_path):
        with CollectorStore(tmp_path / "live.duckdb") as s:
            assert s.put_quotes([]) == 0

    def test_a_session_records_its_own_outcome(self, tmp_path):
        with CollectorStore(tmp_path / "live.duckdb") as s:
            s.start_session("r1")
            s.finish_session("r1", captured=5, polls=2, note="ok")
            row = s.db.execute(
                "SELECT captured, polls, note FROM sessions WHERE run_id='r1'"
            ).fetchone()
            assert row == (5, 2, "ok")


class TestHeartbeatSemantics:
    class FakeSession:
        def __init__(self, code=200, boom=None):
            self.code, self.boom, self.urls = code, boom, []

        def get(self, url, timeout=None):
            self.urls.append(url)
            if self.boom:
                raise self.boom
            return type("R", (), {"status_code": self.code})()

    def test_success_pings_the_bare_url(self):
        sess = self.FakeSession()
        hb = Heartbeat("https://hc.example/abc", session=sess)
        assert hb.ping(ok=True) is True
        assert sess.urls == ["https://hc.example/abc"]

    def test_failure_pings_the_fail_endpoint(self):
        sess = self.FakeSession()
        hb = Heartbeat("https://hc.example/abc", session=sess)
        hb.ping(ok=False)
        assert sess.urls == ["https://hc.example/abc/fail"]

    def test_an_unconfigured_heartbeat_is_reported_not_silent(self):
        hb = Heartbeat(None)
        assert hb.configured is False
        assert hb.ping() is False
        assert "not set" in hb.last_error

    def test_a_network_error_never_raises_into_the_run(self):
        """Failing to REPORT success is not a reason to discard captured data."""
        hb = Heartbeat("https://hc.example/abc",
                       session=self.FakeSession(boom=OSError("dns")))
        assert hb.ping() is False
        assert "OSError" in hb.last_error

    def test_a_non_2xx_is_treated_as_undelivered(self):
        hb = Heartbeat("https://hc.example/abc", session=self.FakeSession(code=500))
        assert hb.ping() is False
        assert "500" in hb.last_error


class TestHeartbeatProviders:
    """Providers are NOT interchangeable, and guessing wrong fails silently.

    The whole point of a dead-man's switch is that the monitor is right about
    whether the run happened. A URL shape that the provider ignores leaves the
    check green while the collector is dead, which is worse than having no
    monitor at all because it actively reassures.
    """

    class FakeSession:
        def __init__(self):
            self.urls = []

        def get(self, url, timeout=None):
            self.urls.append(url)
            return type("R", (), {"status_code": 200})()

    def test_healthchecks_is_the_default(self):
        hb = Heartbeat("https://hc.example/abc")
        assert hb.provider == "healthchecks"
        assert hb.target(ok=True) == "https://hc.example/abc"
        assert hb.target(ok=False) == "https://hc.example/abc/fail"

    def test_cronitor_uses_a_query_parameter_not_a_path(self):
        """Appending /fail to a Cronitor URL hits nothing and stays green."""
        hb = Heartbeat("https://cronitor.link/p/abc", provider="cronitor")
        assert hb.target(ok=True) == "https://cronitor.link/p/abc?state=complete"
        assert hb.target(ok=False) == "https://cronitor.link/p/abc?state=fail"

    def test_cronitor_respects_an_existing_query_string(self):
        hb = Heartbeat("https://cronitor.link/p/abc?env=prod", provider="cronitor")
        assert hb.target(ok=True).endswith("?env=prod&state=complete")

    def test_betterstack_stays_silent_on_failure(self):
        """It has no failure path, so pinging would REPORT SUCCESS."""
        hb = Heartbeat("https://uptime.example/hb", provider="betterstack")
        assert hb.target(ok=True) == "https://uptime.example/hb"
        assert hb.target(ok=False) is None

    def test_silence_on_failure_sends_no_request_at_all(self):
        sess = self.FakeSession()
        hb = Heartbeat("https://uptime.example/hb", provider="betterstack",
                       session=sess)
        assert hb.ping(ok=False) is False
        assert sess.urls == [], "a failed run must not ping a no-fail provider"
        assert "no failure channel" in hb.last_error

    def test_silence_is_recorded_as_deliberate_not_as_an_error(self):
        hb = Heartbeat("https://uptime.example/hb", provider="plain")
        hb.ping(ok=False)
        assert "alerts on absence" in hb.last_error

    def test_success_still_pings_a_no_fail_provider(self):
        sess = self.FakeSession()
        hb = Heartbeat("https://uptime.example/hb", provider="plain", session=sess)
        assert hb.ping(ok=True) is True
        assert sess.urls == ["https://uptime.example/hb"]

    def test_an_unknown_provider_raises_instead_of_guessing(self):
        with pytest.raises(ValueError, match="unknown heartbeat provider"):
            Heartbeat("https://x.example/abc", provider="nope")

    def test_the_provider_is_selectable_by_env_var(self, monkeypatch):
        """Switching provider must be an env var, not a code change."""
        monkeypatch.setenv("CHIRA_HEARTBEAT_PROVIDER", "cronitor")
        assert Heartbeat("https://x.example/abc").provider == "cronitor"

    def test_an_explicit_provider_beats_the_env_var(self, monkeypatch):
        monkeypatch.setenv("CHIRA_HEARTBEAT_PROVIDER", "cronitor")
        hb = Heartbeat("https://x.example/abc", provider="healthchecks")
        assert hb.provider == "healthchecks"

    def test_an_empty_env_var_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("CHIRA_HEARTBEAT_PROVIDER", "")
        assert Heartbeat("https://x.example/abc").provider == "healthchecks"

    def test_every_provider_handles_both_outcomes(self):
        """A provider that crashed on one outcome would be found in production."""
        for name in HEARTBEAT_PROVIDERS:
            hb = Heartbeat("https://x.example/abc", provider=name)
            hb.target(ok=True)
            hb.target(ok=False)

    def test_an_unconfigured_url_has_no_target_for_any_provider(self):
        for name in HEARTBEAT_PROVIDERS:
            hb = Heartbeat(None, provider=name)
            assert hb.target(ok=True) is None


class TestZeroCaptureRule:
    def test_zero_during_an_open_window_is_a_failure(self):
        assert zero_capture_is_a_failure(0, now=utc(2026, 12, 1, 22, 0),
                                         windows=WINDOWS)

    def test_zero_off_season_is_correct_not_a_failure(self):
        """Failing here would train the reader to ignore red runs."""
        assert not zero_capture_is_a_failure(0, now=utc(2026, 7, 4, 22, 0),
                                             windows=WINDOWS)

    def test_zero_outside_the_daily_window_is_not_a_failure(self):
        assert not zero_capture_is_a_failure(0, now=utc(2026, 12, 1, 15, 0),
                                             windows=WINDOWS)

    def test_any_capture_is_never_a_failure(self):
        assert not zero_capture_is_a_failure(1, now=utc(2026, 12, 1, 22, 0),
                                             windows=WINDOWS)


class TestTargetSelection:
    def test_a_game_inside_the_lookahead_is_polled(self):
        now = utc(2026, 12, 1, 22, 0)
        games = [{"game_id": "1", "start_time_utc": now + timedelta(hours=2)}]
        assert len(upcoming_targets(games, now=now)) == 1

    def test_a_game_far_in_the_future_is_not_polled_yet(self):
        now = utc(2026, 12, 1, 22, 0)
        games = [{"game_id": "1", "start_time_utc": now + timedelta(hours=30)}]
        assert upcoming_targets(games, now=now) == []

    def test_a_long_finished_game_is_dropped(self):
        now = utc(2026, 12, 1, 22, 0)
        games = [{"game_id": "1", "start_time_utc": now - timedelta(hours=3)}]
        assert upcoming_targets(games, now=now) == []

    def test_a_just_started_game_is_kept_within_grace(self):
        """Tipoff times move; a game that started late is still quotable."""
        now = utc(2026, 12, 1, 22, 0)
        games = [{"game_id": "1", "start_time_utc": now - timedelta(minutes=10)}]
        assert len(upcoming_targets(games, now=now)) == 1

    def test_an_unknown_start_time_is_KEPT(self):
        """Dropping these would silently exclude postponed and moved games."""
        now = utc(2026, 12, 1, 22, 0)
        assert len(upcoming_targets([{"game_id": "1", "start_time_utc": None}],
                                    now=now)) == 1

    def test_an_iso_string_start_time_is_accepted(self):
        now = utc(2026, 12, 1, 22, 0)
        games = [{"game_id": "1",
                  "start_time_utc": (now + timedelta(hours=1)).isoformat()}]
        assert len(upcoming_targets(games, now=now)) == 1

    def test_a_naive_start_time_is_refused(self):
        now = utc(2026, 12, 1, 22, 0)
        games = [{"game_id": "1", "start_time_utc": datetime(2026, 12, 1, 23, 0)}]
        with pytest.raises(ValueError, match="naive"):
            upcoming_targets(games, now=now)


class TestPollPacing:
    def test_the_delay_does_not_drift_with_slow_polls(self):
        """Measured from the interval boundary, not from the poll's end.

        Otherwise a slow poll pushes every later poll later and quietly
        shortens the session's coverage of the slate.
        """
        assert next_poll_delay(0, interval=300) == 300
        assert next_poll_delay(30, interval=300) == 270
        assert next_poll_delay(299, interval=300) == pytest.approx(1)

    def test_an_overrunning_poll_never_returns_a_negative_delay(self):
        assert next_poll_delay(700, interval=300) == pytest.approx(200)
        assert next_poll_delay(600, interval=300) == 300

    def test_zone_constants_are_real_zones(self):
        assert ZoneInfo("America/New_York") == ET
        assert ZoneInfo("UTC") == UTC
