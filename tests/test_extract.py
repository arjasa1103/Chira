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
    def test_passing_pair_is_recorded(self):
        c = FakeClient({"2020": [{"t": TIP, "p": 0.585}], "1010": [{"t": TIP, "p": 0.415}]})
        r = closing_price(c, MKT)
        assert r["complement_ok"] is True
        assert r["complement_sum"] == pytest.approx(1.0)

    def test_violation_is_flagged_with_the_sum(self):
        c = FakeClient({"2020": [{"t": TIP, "p": 0.585}], "1010": [{"t": TIP, "p": 0.500}]})
        r = closing_price(c, MKT)
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
