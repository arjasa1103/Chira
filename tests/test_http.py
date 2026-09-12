"""Tests for the rate-limited client: when to retry, and when to stop.

The retry/circuit logic decides whether a 15,300-request census survives a
hiccup or gets the caller's IP blocked, and none of it was covered. Every
response here is stubbed; conftest blocks real sockets.
"""

from __future__ import annotations

import json

import pytest

from chira import http as http_mod
from chira.http import (
    BACKOFF_CAP,
    CIRCUIT_BREAK_AFTER,
    CircuitOpen,
    Client,
    TransientError,
    _retry_after_seconds,
)


class Resp:
    def __init__(self, code, ctype="application/json", body=None, headers=None):
        self.status_code = code
        self.headers = {"content-type": ctype, **(headers or {})}
        self._body = body

    def json(self):
        if self._body is None:
            raise json.JSONDecodeError("no body", "", 0)
        return self._body


@pytest.fixture
def client(monkeypatch):
    """Fast client with sleeps neutered."""
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)
    return Client(rate_rps=1e6)


def stub(monkeypatch, c, responses):
    it = iter(responses)
    monkeypatch.setattr(c.s, "get", lambda *a, **k: next(it))


class TestConstructorGuards:
    @pytest.mark.parametrize("bad", [0, -1, -0.5])
    def test_non_positive_rate_is_rejected(self, bad):
        with pytest.raises(ValueError, match="positive"):
            Client(rate_rps=bad)

    @pytest.mark.parametrize("bad", [0, -1])
    def test_max_attempts_below_one_is_rejected(self, client, bad):
        """Previously fell through the loop and raised UnboundLocalError."""
        with pytest.raises(ValueError, match="max_attempts"):
            client.get_json("https://x", max_attempts=bad)


class TestSuccessPath:
    def test_json_200_returns_the_body_and_counts_it(self, client, monkeypatch):
        stub(monkeypatch, client, [Resp(200, body={"ok": 1})])
        assert client.get_json("https://x") == {"ok": 1}
        assert client.stats["http:200"] == 1

    def test_a_success_resets_the_consecutive_failure_counter(self, client, monkeypatch):
        stub(monkeypatch, client, [Resp(503), Resp(503), Resp(200, body=[])])
        assert client.get_json("https://x") == []
        assert client._consecutive_failures == 0


class TestWafAndMalformedResponses:
    def test_non_json_200_is_transient_and_never_a_miss(self, client, monkeypatch):
        """A WAF challenge page returns 200 with HTML.

        Recording that as "no market exists" fabricates a miss AND keeps the
        census reconciliation assert perfectly balanced while the data is wrong.
        """
        stub(monkeypatch, client, [Resp(200, "text/html")] * 4)
        with pytest.raises(TransientError):
            client.get_json("https://x")
        assert client.stats["nonjson200"] == 4

    def test_undecodable_json_200_is_transient(self, client, monkeypatch):
        stub(monkeypatch, client, [Resp(200)] * 4)
        with pytest.raises(TransientError):
            client.get_json("https://x")
        assert client.stats["badjson"] == 4

    def test_a_transient_run_that_recovers_returns_normally(self, client, monkeypatch):
        stub(monkeypatch, client, [Resp(200, "text/html"), Resp(200, body={"v": 2})])
        assert client.get_json("https://x") == {"v": 2}


class TestStatusHandling:
    def test_an_unlisted_4xx_raises_immediately_without_retrying(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(client.s, "get", lambda *a, **k: calls.append(1) or Resp(404))
        with pytest.raises(RuntimeError, match="404"):
            client.get_json("https://x")
        assert len(calls) == 1, "a 404 must not be retried"

    def test_a_403_counts_toward_the_circuit_on_every_occurrence(self, client, monkeypatch):
        """A WAF 403 is an IP block, not congestion.

        Retrying it is how a soft throttle becomes a ban, so it must not get the
        same generous budget as a 503.
        """
        monkeypatch.setattr(client.s, "get", lambda *a, **k: Resp(403))
        with pytest.raises(CircuitOpen, match="403"):
            client.get_json("https://x")

    def test_repeated_5xx_eventually_opens_the_circuit(self, client, monkeypatch):
        monkeypatch.setattr(client.s, "get", lambda *a, **k: Resp(503))
        for _ in range(CIRCUIT_BREAK_AFTER - 1):
            with pytest.raises(TransientError):
                client.get_json("https://x")
        with pytest.raises(CircuitOpen):
            client.get_json("https://x")

    def test_repeated_non_retryable_errors_also_open_the_circuit(self, client, monkeypatch):
        """Previously five 404s raised five bare RuntimeErrors and never CircuitOpen."""
        monkeypatch.setattr(client.s, "get", lambda *a, **k: Resp(400))
        for _ in range(CIRCUIT_BREAK_AFTER - 1):
            with pytest.raises(RuntimeError):
                client.get_json("https://x")
        with pytest.raises(CircuitOpen):
            client.get_json("https://x")

    def test_the_circuit_message_does_not_promise_saved_state(self, client, monkeypatch):
        monkeypatch.setattr(client.s, "get", lambda *a, **k: Resp(403))
        with pytest.raises(CircuitOpen) as e:
            client.get_json("https://x")
        assert "parking" not in str(e.value).lower(), "nothing is persisted yet"
        assert "NO state saved" in str(e.value)

    def test_a_network_exception_is_transient_and_counted(self, client, monkeypatch):
        import requests

        def boom(*a, **k):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(client.s, "get", boom)
        with pytest.raises(TransientError):
            client.get_json("https://x")
        assert client.stats["exc:ConnectionError"] == 4


class TestRetryAfter:
    def test_delta_seconds_is_honoured_up_to_the_cap(self):
        assert _retry_after_seconds("5", 2) == 5.0
        assert _retry_after_seconds("99999", 2) == BACKOFF_CAP

    def test_the_http_date_form_is_parsed_not_swallowed(self):
        """RFC 9110 permits a date. float() rejects it, and swallowing that left
        the client retrying on a stale 2s backoff against a longer instruction."""
        v = _retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT", 2)
        assert 0.0 <= v <= BACKOFF_CAP

    def test_an_unparseable_value_backs_off_maximally(self):
        assert _retry_after_seconds("soon", 2) == BACKOFF_CAP

    def test_a_past_date_does_not_produce_a_negative_backoff(self):
        assert _retry_after_seconds("Wed, 21 Oct 2020 07:28:00 GMT", 2) >= 0.0


class TestUrlConstruction:
    def test_a_non_numeric_token_id_is_rejected(self, client):
        """token_id comes from remote data. An unencoded & would rewrite the
        query and the resulting empty history would be recorded as a real miss."""
        for bad in ["abc", "123&fidelity=99", "1 2", "", "12#x"]:
            with pytest.raises(ValueError, match="numeric"):
                client.prices_history(bad, 0)

    def test_parameters_are_percent_encoded(self, client, monkeypatch):
        seen = {}

        def cap(url, *a, **k):
            seen["url"] = url
            return Resp(200, body=[])

        monkeypatch.setattr(client.s, "get", cap)
        client.event_by_slug("nba-was-okc-2025-10-30")
        assert "slug=nba-was-okc-2025-10-30" in seen["url"]
        client.markets(end_date_min="2025-12-01T00:00:00Z")
        assert "closed=true" in seen["url"]
        assert "%3A" in seen["url"], "the timestamp colons must be encoded"

    def test_prices_history_sends_start_ts_not_interval(self, client, monkeypatch):
        """interval=max with fine fidelity silently returns [] for old markets."""
        seen = {}
        monkeypatch.setattr(client.s, "get",
                            lambda url, *a, **k: (seen.__setitem__("url", url),
                                                  Resp(200, body={"history": []}))[1])
        client.prices_history("12345", 1700000000)
        assert "startTs=1700000000" in seen["url"]
        assert "interval=" not in seen["url"]

    def test_prices_history_unwraps_the_history_key(self, client, monkeypatch):
        stub(monkeypatch, client, [Resp(200, body={"history": [{"t": 1, "p": 0.5}]})])
        assert client.prices_history("1", 0) == [{"t": 1, "p": 0.5}]

    def test_a_non_list_market_response_becomes_an_empty_list(self, client, monkeypatch):
        stub(monkeypatch, client, [Resp(200, body={"unexpected": True})])
        assert client.markets() == []
