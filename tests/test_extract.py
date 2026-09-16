"""Tests for closing-price extraction: the function that produces the product.

Everything downstream is arithmetic on this output, and the orientation chain
(slug -> outcomes -> clobTokenIds -> outcomePrices, all index-aligned) fails
SILENTLY when it fails: under a home-side-only convention an orientation flip
mirrors the calibration curve about 0.5 instead of crashing.
"""

from __future__ import annotations

import time

import pytest

from chira.constants import STALE_FLAT_RUN
from chira.extract import _parse_gst, closing_price, label_agreement

TIP_ISO = "2025-10-30 23:00:00+00"
TIP = 1761865200.0  # 2025-10-30T23:00:00Z
MKT = {
    "clobTokenIds": '["1010","2020"]',
    "outcomes": '["Wizards","Thunder"]',
    "gameStartTime": TIP_ISO,
}


class FakeClient:
    """Stands in for chira.http.Client. conftest blocks real sockets."""

    def __init__(self, by_token: dict[str, list[dict]]):
        self.by_token = by_token
        self.calls: list[str] = []

    def prices_history(self, token, start_ts, fidelity=1, *, bypass_cache=False):
        # Signature mirrors the real Client, bypass_cache included: a fake that
        # has drifted from the interface is a test passing against code that
        # no longer exists.
        self.calls.append(token)
        return self.by_token.get(token, [])


def _pts(n: int, *, flat: bool = True, base: float = 0.60, end: float = TIP) -> list[dict]:
    """n minute points ending exactly at `end`."""
    return [
        {"t": end - (n - 1 - i) * 60, "p": base if flat else base + i * 0.001}
        for i in range(n)
    ]


class TestOrientation:
    def test_home_is_index_one_on_both_tokens_and_outcomes(self):
        c = FakeClient({"2020": [{"t": TIP, "p": 0.62}], "1010": [{"t": TIP, "p": 0.38}]})
        r = closing_price(c, MKT)
        assert r["home_nickname"] == "Thunder"
        assert r["away_nickname"] == "Wizards"
        assert r["p_home_close"] == 0.62
        assert "2020" in c.calls, "the home series must come from clobTokenIds[1]"

    def test_a_point_exactly_at_tipoff_is_pre_tipoff(self):
        """Off by one here leaks the result into the 'closing' price."""
        c = FakeClient({
            "2020": [{"t": TIP - 60, "p": 0.60}, {"t": TIP, "p": 0.62}, {"t": TIP + 60, "p": 0.99}],
            "1010": [{"t": TIP, "p": 0.38}],
        })
        r = closing_price(c, MKT)
        assert r["p_home_close"] == 0.62, "post-tipoff point must be excluded"
        assert r["n_pre_tipoff"] == 2
        assert r["secs_before_tip"] == 0


class TestT1hConstruction:
    def test_picks_the_last_point_at_or_before_one_hour_out(self):
        c = FakeClient({
            "2020": [{"t": TIP - 7200, "p": 0.50}, {"t": TIP - 3600, "p": 0.55},
                     {"t": TIP - 1800, "p": 0.58}, {"t": TIP, "p": 0.62}],
            "1010": [],
        })
        assert closing_price(c, MKT)["p_home_t1h"] == 0.55

    def test_is_none_when_the_market_opened_inside_the_hour(self):
        c = FakeClient({"2020": [{"t": TIP - 10, "p": 0.6}], "1010": []})
        assert closing_price(c, MKT)["p_home_t1h"] is None


class TestStaleness:
    @pytest.mark.parametrize("n,flat,expect", [
        (STALE_FLAT_RUN, True, True),
        (STALE_FLAT_RUN + 1, True, True),
        (STALE_FLAT_RUN, False, False),
        (STALE_FLAT_RUN - 1, True, False),  # short series cannot be judged
        (1, True, False),
    ])
    def test_flat_run_boundaries(self, n, flat, expect):
        c = FakeClient({"2020": _pts(n, flat=flat), "1010": []})
        assert closing_price(c, MKT)["stale_flat_run"] is expect


class TestComplementarity:
    @staticmethod
    def _simultaneous(home_p, away_p, n=12):
        """n simultaneous minute quotes: the check needs >= 10 pairs to judge."""
        ts = [TIP - 60 * i for i in range(n)][::-1]
        return ([{"t": t, "p": home_p} for t in ts], [{"t": t, "p": away_p} for t in ts])

    def test_passing_pair_is_recorded(self):
        home, away = self._simultaneous(0.585, 0.415)
        r = closing_price(FakeClient({"2020": home, "1010": away}), MKT)
        assert r["complement_ok"] is True
        assert r["complement_sum"] == pytest.approx(1.0)

    def test_violation_is_flagged_with_the_sum(self):
        home, away = self._simultaneous(0.585, 0.500)
        r = closing_price(FakeClient({"2020": home, "1010": away}), MKT)
        assert r["complement_ok"] is False
        assert r["complement_sum"] == pytest.approx(1.085)

    def test_missing_away_series_is_none_not_silently_passing(self):
        """None must be distinguishable from True, or a skipped check reads as a pass."""
        c = FakeClient({"2020": [{"t": TIP, "p": 0.6}], "1010": []})
        r = closing_price(c, MKT)
        assert r["complement_ok"] is None
        assert r["complement_reason"] == "no_away_series"


class TestResolutionLabel:
    @pytest.mark.parametrize("op,winner,excluded", [
        ('["0","1"]', "home", None),
        ('["1","0"]', "away", None),
        # Regression: ["0.5","0.5"] sums to exactly 1.0, so a complementarity-first
        # ordering made the exclusion branch unreachable and labelled this an AWAY WIN.
        ('["0.5","0.5"]', None, "postponed_or_split_resolution"),
        ('["0.3","0.3"]', None, "outcome_prices_not_complementary"),
        ('["0.2","0.5"]', None, "outcome_prices_not_complementary"),
        ('["1","0","0"]', None, "malformed_outcome_prices"),
    ])
    def test_every_outcome_price_shape_has_a_distinct_verdict(self, op, winner, excluded):
        c = FakeClient({"2020": [{"t": TIP, "p": 0.6}], "1010": [{"t": TIP, "p": 0.4}]})
        r = closing_price(c, {**MKT, "outcomePrices": op})
        assert r["market_winner"] == winner
        assert r.get("reason_excluded") == excluded

    def test_a_postponed_game_never_reports_a_winner(self):
        c = FakeClient({"2020": [{"t": TIP, "p": 0.6}], "1010": [{"t": TIP, "p": 0.4}]})
        r = closing_price(c, {**MKT, "outcomePrices": '["0.5","0.5"]'})
        assert r["market_winner"] is None, "a tie must never become y=0 in the sample"


class TestMalformedInputNeverRaises:
    """A census is ~15,300 requests. One bad row must not abort it."""

    @pytest.mark.parametrize("mkt,reason", [
        ({}, "unparseable_market"),
        ({"outcomes": '["a","b"]', "gameStartTime": TIP_ISO}, "unparseable_market"),
        ({"clobTokenIds": '["a","b"', "outcomes": '["a","b"]',
          "gameStartTime": TIP_ISO}, "unparseable_market"),
        ({"clobTokenIds": '["a","b"]', "outcomes": '["a"]',
          "gameStartTime": TIP_ISO}, "unparseable_market"),
        ({"clobTokenIds": '["a","b"]', "outcomes": '["a","b","c"]',
          "gameStartTime": TIP_ISO}, "unparseable_market"),
        # Token ids must be decimal strings: a hex or placeholder id used to
        # raise ValueError out of prices_history and abort the census.
        ({"clobTokenIds": '["0xdead","0xbeef"]', "outcomes": '["a","b"]',
          "gameStartTime": TIP_ISO}, "unparseable_market"),
        ({"clobTokenIds": '[null,"2020"]', "outcomes": '["a","b"]',
          "gameStartTime": TIP_ISO}, "unparseable_market"),
        ({"clobTokenIds": '["1010","2020"]', "outcomes": '["a","b"]'},
         "missing_gameStartTime"),
        ({"clobTokenIds": '["1010","2020"]', "outcomes": '["a","b"]',
          "gameStartTime": "not-a-date"}, "unparseable_gameStartTime"),
    ])
    def test_returns_a_sentinel_with_a_distinct_reason(self, mkt, reason):
        r = closing_price(FakeClient({}), mkt)
        assert r["ok"] is False
        assert r["reason"] == reason

    def test_a_real_list_instead_of_a_json_string_is_tolerated(self):
        """Defensive: an upstream change to real arrays must not crash the census."""
        c = FakeClient({"2020": [{"t": TIP, "p": 0.6}], "1010": []})
        r = closing_price(c, {**MKT, "clobTokenIds": ["1010", "2020"]})
        assert r["ok"] is True

    def test_price_points_of_the_wrong_shape_are_dropped_not_fatal(self):
        c = FakeClient({"2020": [{"t": "notanumber", "p": 0.5}, {"p": 0.5},
                                 "junk", {"t": TIP, "p": 0.61}], "1010": []})
        r = closing_price(c, MKT)
        assert r["ok"] is True
        assert r["n_pre_tipoff"] == 1
        assert r["p_home_close"] == 0.61


class TestTimestampParsing:
    def test_both_observed_formats_parse(self):
        assert _parse_gst("2025-12-01 02:00:00+00") is not None
        assert _parse_gst("2025-11-24T15:01:58.050026Z") is not None

    def test_a_naive_timestamp_is_rejected(self):
        """.timestamp() on a naive datetime uses the HOST zone.

        Measured: the same offset-less string produced epochs 7 hours apart
        between TZ=America/Los_Angeles and UTC. That epoch is the pre-tipoff
        cutoff, so a naive value could place "closing" after tipoff.
        """
        assert _parse_gst("2025-10-30 23:00:00") is None

    @pytest.mark.skipif(not hasattr(time, "tzset"),
                        reason="no time.tzset on Windows: TZ cannot change the "
                               "process zone, so this would pass without testing")
    @pytest.mark.parametrize("tz", ["UTC", "America/Los_Angeles", "Asia/Tokyo"])
    def test_tipoff_epoch_is_host_timezone_independent(self, tz, monkeypatch):
        monkeypatch.setenv("TZ", tz)
        if hasattr(time, "tzset"):
            time.tzset()
        assert _parse_gst(TIP_ISO).timestamp() == TIP

    def test_garbage_returns_none_rather_than_raising(self):
        for bad in ["", "not-a-date", None, "2025-13-45"]:
            assert _parse_gst(bad) is None


class TestLabelAgreement:
    @pytest.mark.parametrize("mw,sw,expect", [
        ("home", "home", "agree"),
        ("away", "away", "agree"),
        ("home", "away", "disagree"),
        ("away", "home", "disagree"),
        (None, "home", "unresolved"),
        (None, "away", "unresolved"),
    ])
    def test_table(self, mw, sw, expect):
        assert label_agreement(mw, sw) == expect


class TestTimeToCloseLooks:
    """PREREGISTRATION section 8 treats close, T-1h, T-6h, T-24h as four looks at one
    sample. Week 2 extracted two of them."""

    def _market_series(self, hours_back: float):
        n = int(hours_back * 60) + 1
        return [{"t": TIP - (n - 1 - i) * 60, "p": round(0.40 + i / (10 * n), 6)}
                for i in range(n)]

    def test_each_look_is_the_last_point_at_or_before_its_offset(self):
        home = self._market_series(30)
        c = FakeClient({"2020": home, "1010": [{"t": TIP, "p": 0.5}]})
        r = closing_price(c, MKT)
        for key, secs in (("p_home_t1h", 3600), ("p_home_t6h", 21600),
                          ("p_home_t24h", 86400)):
            want = [pt["p"] for pt in home if pt["t"] <= TIP - secs][-1]
            assert r[key] == want, key

    def test_a_market_that_opened_inside_the_window_reports_none(self):
        """Countable, not zero-filled: a market open 3 hours has no T-6h."""
        c = FakeClient({"2020": self._market_series(3), "1010": [{"t": TIP, "p": 0.5}]})
        r = closing_price(c, MKT)
        assert r["p_home_t1h"] is not None
        assert r["p_home_t6h"] is None and r["p_home_t24h"] is None


class TestRawSeries:
    """The raw series ships in the snapshot (PLAN.md F10), so it is returned whole."""

    def test_post_tipoff_points_are_kept_in_the_series_but_not_in_the_close(self):
        home = [{"t": TIP - 60, "p": 0.60}, {"t": TIP + 60, "p": 0.99}]
        c = FakeClient({"2020": home, "1010": [{"t": TIP - 60, "p": 0.40}]})
        r = closing_price(c, MKT)
        assert r["p_home_close"] == 0.60, "post-tipoff leaked into the close"
        assert [pt["t"] for pt in r["series"]["home"]] == [TIP - 60, TIP + 60]

    def test_the_series_is_sorted_even_if_the_api_is_not(self):
        home = [{"t": TIP, "p": 0.6}, {"t": TIP - 120, "p": 0.5}, {"t": TIP - 60, "p": 0.55}]
        r = closing_price(FakeClient({"2020": home, "1010": home}), MKT)
        ts = [pt["t"] for pt in r["series"]["home"]]
        assert ts == sorted(ts)
        assert r["p_home_close"] == 0.6

    @pytest.mark.parametrize("bad_p", [float("nan"), float("inf"), -0.1, 1.5, True, "0.5"])
    def test_invalid_prices_never_reach_the_series(self, bad_p):
        """json.loads accepts bare NaN/Infinity; the series is a published artifact."""
        home = [{"t": TIP - 120, "p": 0.5}, {"t": TIP - 60, "p": bad_p}]
        r = closing_price(FakeClient({"2020": home, "1010": home}), MKT)
        assert [pt["p"] for pt in r["series"]["home"]] == [0.5]
        assert r["p_home_close"] == 0.5


class TestLeagueCutoff:
    """PREREGISTRATION.md Amendment 1."""

    def _home(self):
        return [{"t": TIP - 120, "p": 0.55}, {"t": TIP - 60, "p": 0.60},
                {"t": TIP + 3600, "p": 0.99}]  # the last point is in-game

    def test_a_late_gamma_tipoff_no_longer_leaks_the_game_into_the_close(self):
        mkt = dict(MKT, gameStartTime="2025-10-31T01:00:00+00:00")   # Gamma 2h LATE
        c = FakeClient({"2020": self._home(), "1010": [{"t": TIP - 60, "p": 0.40}]})
        r = closing_price(c, mkt, tip_utc="2025-10-30T23:00:00Z")
        assert r["cutoff_source"] == "league"
        assert r["p_home_close"] == 0.60, "the league cutoff must exclude in-game quotes"
        assert r["p_home_close_gamma"] == 0.99, "the audit column keeps the original definition"
        assert r["gamma_delta_min"] == 120

    def test_an_early_gamma_tipoff_is_measured_with_a_negative_delta(self):
        mkt = dict(MKT, gameStartTime="2025-10-30T19:00:00+00:00")   # 4h EARLY
        c = FakeClient({"2020": [{"t": TIP - 4 * 3600 - 60, "p": 0.50}, {"t": TIP - 60, "p": 0.61}],
                        "1010": [{"t": TIP - 60, "p": 0.39}]})
        r = closing_price(c, mkt, tip_utc="2025-10-30T23:00:00Z")
        assert (r["p_home_close"], r["p_home_close_gamma"], r["gamma_delta_min"]) == (
            0.61, 0.50, -240)

    def test_a_league_time_prices_a_market_with_no_gameStartTime(self):
        mkt = {k: v for k, v in MKT.items() if k != "gameStartTime"}
        c = FakeClient({"2020": self._home(), "1010": [{"t": TIP - 60, "p": 0.4}]})
        r = closing_price(c, mkt, tip_utc="2025-10-30T23:00:00Z")
        assert r["ok"] and r["cutoff_source"] == "league"
        assert r["gamma_delta_min"] is None and r["p_home_close_gamma"] is None

    def test_an_unparseable_league_time_falls_back_to_gamma_and_says_so(self):
        c = FakeClient({"2020": self._home(), "1010": [{"t": TIP - 60, "p": 0.4}]})
        r = closing_price(c, MKT, tip_utc="not-a-time")
        assert r["cutoff_source"] == "gamma" and r["p_home_close"] == 0.60

    def test_no_league_time_is_the_original_definition(self):
        c = FakeClient({"2020": self._home(), "1010": [{"t": TIP - 60, "p": 0.4}]})
        r = closing_price(c, MKT)
        assert r["cutoff_source"] == "gamma" and r["gamma_delta_min"] == 0
        assert r["p_home_close"] == r["p_home_close_gamma"] == 0.60


class TestComplementarityOnSimultaneousQuotes:
    """Pairs within 60 s in the last 2 h; pass when >= 50% sum to exactly 1."""

    @staticmethod
    def _pair_series(n, *, home_p=0.60, away_p=None, away_lag=5, step=60, end=None):
        end = TIP - 30 if end is None else end
        home = [{"t": end - step * i, "p": home_p} for i in range(n)][::-1]
        ap = (1 - home_p) if away_p is None else away_p
        away = [{"t": end - step * i - away_lag, "p": ap} for i in range(n)][::-1]
        return home, away

    def test_quotes_seconds_apart_that_sum_to_one_pass(self):
        home, away = self._pair_series(20)
        r = closing_price(FakeClient({"2020": home, "1010": away}), MKT)
        assert (r["complement_ok"], r["complement_share"], r["complement_pairs"]) == (True, 1.0, 20)

    def test_price_moving_between_samples_still_passes(self):
        """The worst correct game measured: share 0.5755, per-pair error <= 0.03."""
        home, away = self._pair_series(20)
        for pt in away[:6]:
            pt["p"] = 0.395   # 6 of 20 pairs off by 0.005
        r = closing_price(FakeClient({"2020": home, "1010": away}), MKT)
        assert r["complement_ok"] is True and r["complement_share"] == 0.7

    def test_a_non_complementary_market_fails(self):
        home, away = self._pair_series(20, away_p=0.30)
        r = closing_price(FakeClient({"2020": home, "1010": away}), MKT)
        assert r["complement_ok"] is False and r["complement_share"] == 0.0
        assert r["complement_sum"] == 0.9

    def test_too_few_simultaneous_quotes_is_unchecked(self):
        home, away = self._pair_series(3)
        r = closing_price(FakeClient({"2020": home, "1010": away}), MKT)
        assert r["complement_ok"] is None
        assert r["complement_reason"] == "too_few_simultaneous_quotes"

    def test_quotes_more_than_60s_apart_do_not_pair(self):
        home, away = self._pair_series(20, away_lag=61, step=300)
        r = closing_price(FakeClient({"2020": home, "1010": away}), MKT)
        assert r["complement_pairs"] == 0 and r["complement_ok"] is None

    def test_quotes_older_than_two_hours_are_ignored(self):
        home, away = self._pair_series(20, end=TIP - 3 * 3600)
        r = closing_price(FakeClient({"2020": home, "1010": away}), MKT)
        assert r["complement_pairs"] == 0 and r["complement_ok"] is None

    def test_post_tipoff_quotes_are_ignored(self):
        home, away = self._pair_series(20, away_p=0.30, end=TIP + 30 * 60)
        pre_h, pre_a = self._pair_series(12)
        r = closing_price(FakeClient({"2020": pre_h + home, "1010": pre_a + away}), MKT)
        assert r["complement_ok"] is True and r["complement_pairs"] == 12
