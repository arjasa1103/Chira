"""Tests for the census runner: how a game becomes a price or a classified miss.

Every branch here is a way the coverage number can be wrong. The one that
matters most is `label_disagreement`: the market and the league disagreeing
about who won means either the orientation chain is flipped or the slug matched
the wrong game, and both look like findings rather than bugs.

No network: the client is a dict-backed stub.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from chira.census import (
    census_game,
    load_abbr_map,
    manifest,
    rematch_slugs,
    reprobe_misses,
    run_census,
    slice_games,
    tipoff_is_plausible,
)
from chira.store import Store
from chira.telemetry import Telemetry

TIP = "2025-01-16T00:30:00Z"
TIP_TS = 1736987400  # = datetime.fromisoformat(TIP).timestamp()


def market(*, outcomes=("Lakers", "Celtics"), tokens=("1", "2"),
           prices=("0", "1"), gst=TIP, volume=123456.0, **kw):
    m = {
        "outcomes": json.dumps(list(outcomes)),
        "clobTokenIds": json.dumps(list(tokens)),
        "gameStartTime": gst,
        "volume": volume,
    }
    if prices is not None:
        m["outcomePrices"] = json.dumps(list(prices))
    m.update(kw)
    return m


def game(gid="g1", **kw):
    base = {"game_id": gid, "et_date": "2025-01-15", "away": "lal", "home": "bos",
            "away_name": "Lakers", "home_name": "Celtics",
            "away_place": "Los Angeles", "home_place": "Boston",
            "away_pts": 100, "home_pts": 110, "winner": "home"}
    return {**base, **kw}


def series(p, n=12, end=TIP_TS - 60):
    return [{"t": end - 60 * (n - 1 - i), "p": p} for i in range(n)]


class FakeClient:
    """Minimal stand-in for http.Client: slug -> events, token -> price points."""

    def __init__(self, events=None, prices=None):
        self.events = events or {}
        self.prices = prices or {}
        self.slugs_tried: list[str] = []
        self.bypassed: list[str] = []

    def event_by_slug(self, slug, *, bypass_cache=False):
        self.slugs_tried.append(slug)
        if bypass_cache:
            self.bypassed.append(slug)
        return self.events.get(slug, [])

    def prices_history(self, token_id, start_ts, fidelity=1, *, bypass_cache=False):
        return self.prices.get(str(token_id), [])


def standard_client(*, slug="nba-lal-bos-2025-01-15", **market_kw):
    """Price series always ends one minute before whatever tipoff the market claims."""
    gst = market_kw.get("gst", TIP)
    tip = datetime.fromisoformat(gst.replace("Z", "+00:00")).timestamp()
    return FakeClient(
        events={slug: [{"markets": [market(**market_kw)]}]},
        prices={"2": series(0.62, end=tip - 60), "1": series(0.38, end=tip - 60)},
    )


@pytest.fixture
def labels():
    return {"lal": ("Lakers", "Los Angeles"), "bos": ("Celtics", "Boston")}


class TestPricedPath:
    def test_a_clean_game_is_priced_with_provenance(self, labels):
        res = census_game(standard_client(), "nba", game(), {}, labels)
        assert res["outcome"] == "priced"
        row = res["row"]
        assert row["slug"] == "nba-lal-bos-2025-01-15"
        assert row["convention"] == "et"
        assert row["p_home_close"] == 0.62
        assert row["label_agreement"] == "agree"
        assert row["complement_ok"] is True
        assert row["volume"] == 123456.0

    def test_the_abbreviation_map_is_applied_to_the_slug(self, labels):
        """The `vgk -> las` case, which is 164 real games."""
        client = FakeClient(
            events={"nhl-lal-las-2025-01-15": [{"markets": [market()]}]},
            prices={"2": series(0.5), "1": series(0.5)})
        res = census_game(client, "nhl", game(home="vgk", home_name="Celtics"),
                          {"vgk": "las"}, {**labels, "vgk": ("Celtics",)})
        assert res["outcome"] == "priced"
        assert res["row"]["slug"] == "nhl-lal-las-2025-01-15"

    def test_the_second_date_convention_is_tried(self, labels):
        client = FakeClient(
            events={"nba-lal-bos-2025-01-16": [{"markets": [market()]}]},
            prices={"2": series(0.62), "1": series(0.38)})
        res = census_game(client, "nba", game(), {}, labels)
        assert res["outcome"] == "priced"
        assert res["row"]["convention"] == "et_plus_1"


class TestMissClassification:
    def test_no_market_records_every_slug_attempted(self, labels):
        res = census_game(FakeClient(), "nba", game(), {}, labels)
        assert res["outcome"] == "miss"
        assert res["reason"] == "no_market"
        assert res["attempted"] == ["nba-lal-bos-2025-01-15", "nba-lal-bos-2025-01-16"]

    def test_a_market_whose_labels_do_not_match_is_its_own_reason(self, labels):
        """A slug can hit and be a different game.

        This must NOT be `no_market`: that bucket is the sole evidence for the
        claim that Polymarket's NHL coverage starts in December 2024, and it
        cannot support it if it also contains "a market is there under labels we
        did not recognise".
        """
        client = FakeClient(
            events={"nba-lal-bos-2025-01-15": [
                {"markets": [market(outcomes=("Knicks", "Heat"))]}]},
            prices={"2": series(0.62)})
        res = census_game(client, "nba", game(), {}, labels)
        assert res["reason"] == "label_mismatch_at_slug"

    def test_an_empty_event_list_is_still_no_market(self, labels):
        assert census_game(FakeClient(), "nba", game(), {}, labels)["reason"] == "no_market"

    def test_a_postponed_game_is_its_own_reason_not_an_away_win(self, labels):
        res = census_game(standard_client(prices=("0.5", "0.5")), "nba",
                          game(), {}, labels)
        assert res["reason"] == "postponed_or_split_resolution"

    def test_a_market_with_no_outcome_prices_is_unresolved_not_priced(self, labels):
        res = census_game(standard_client(prices=None), "nba", game(), {}, labels)
        assert res["reason"] == "unresolved_market"

    def test_an_equal_but_non_complementary_pair_is_not_called_postponed(self, labels):
        """["0.3","0.3"] is a tie that does not sum to 1.

        It must NOT take the postponed branch, which is reserved for the exact
        ["0.5","0.5"] shape. Reporting it as postponed would put a broken market
        on the reconciliation line as a legitimate schedule event.
        """
        res = census_game(standard_client(prices=("0.3", "0.3")), "nba",
                          game(), {}, labels)
        assert res["reason"] == "outcome_prices_not_complementary"

    def test_a_wrong_length_outcome_price_array_is_malformed(self, labels):
        res = census_game(standard_client(prices=("1",)), "nba", game(), {}, labels)
        assert res["reason"] == "malformed_outcome_prices"

    def test_an_empty_price_series_is_a_miss_with_its_own_reason(self, labels):
        client = FakeClient(
            events={"nba-lal-bos-2025-01-15": [{"markets": [market()]}]},
            prices={})
        res = census_game(client, "nba", game(), {}, labels)
        assert res["reason"] == "no_pre_tipoff_points"

    def test_a_failed_complementarity_check_is_a_miss(self, labels):
        client = FakeClient(
            events={"nba-lal-bos-2025-01-15": [{"markets": [market()]}]},
            prices={"2": series(0.62), "1": series(0.10)})
        res = census_game(client, "nba", game(), {}, labels)
        assert res["reason"] == "complementarity_failed"
        assert "sum=" in res["detail"]

    def test_a_malformed_market_does_not_raise(self, labels):
        client = FakeClient(
            events={"nba-lal-bos-2025-01-15": [
                {"markets": [{"outcomes": '["Lakers","Celtics"]',
                              "clobTokenIds": "not json", "gameStartTime": TIP}]}]})
        res = census_game(client, "nba", game(), {}, labels)
        assert res["reason"] == "unparseable_market"

    def test_a_label_disagreement_is_loud_and_never_priced(self, labels):
        """E1. The market says away won, the league says home won."""
        res = census_game(standard_client(prices=("1", "0")), "nba", game(), {}, labels)
        assert res["reason"] == "label_disagreement"
        assert "market=away" in res["detail"] and "league=home" in res["detail"]


class TestTipoffPlausibility:
    """gameStartTime is supplied by the party being benchmarked AND is the
    pre-tipoff cutoff, so a late one admits settled quotes as the closing price."""

    def test_the_live_bad_row_is_now_rejected(self, labels):
        """nba-dal-uta-2024-11-14: 00:57 ET tipoff, p_home_close 0.9995 on a
        115-113 game. A perfect predictor manufactured by a bad timestamp."""
        client = standard_client(slug="nba-lal-bos-2024-11-14",
                                 gst="2024-11-15T05:57:00Z")
        res = census_game(client, "nba", game(et_date="2024-11-14"), {}, labels)
        assert res["reason"] == "implausible_game_start_time"
        assert "ET date" in res["detail"]

    def test_a_morning_faceoff_is_rejected(self, labels):
        """nhl-nsh-pit-2025-11-16 carried a 09:00 ET faceoff, truncating the
        closing price nine hours early."""
        res = census_game(standard_client(gst="2025-01-15T14:00:00Z"), "nba",
                          game(), {}, labels)
        assert res["reason"] == "implausible_game_start_time"
        assert "ET hour" in res["detail"]

    @pytest.mark.parametrize("gst,et_date", [
        ("2025-01-16T00:30:00Z", "2025-01-15"),   # 19:30 ET, the common case
        ("2025-01-15T17:00:00Z", "2025-01-15"),   # 12:00 ET matinee
        ("2025-01-16T03:30:00Z", "2025-01-15"),   # 22:30 ET west coast
    ])
    def test_real_tipoff_shapes_are_accepted(self, labels, gst, et_date):
        res = census_game(standard_client(gst=gst), "nba",
                          game(et_date=et_date), {}, labels)
        assert res["outcome"] == "priced", res

    def test_a_naive_timestamp_is_rejected(self, labels):
        res = census_game(standard_client(gst="2025-01-16 00:30:00"), "nba",
                          game(), {}, labels)
        assert res["reason"] == "implausible_game_start_time"


class TestRematchGuard:
    """19 consecutive-day same-orientation pairs exist; for the earlier game the
    et_plus_1 slug IS the later game's primary slug."""

    def test_the_blocked_slug_is_not_probed_and_is_recorded(self, labels):
        games = [game("g1", et_date="2025-01-15"), game("g2", et_date="2025-01-16")]
        blocked = rematch_slugs("nba", games, {})
        assert blocked == {"g1": "nba-lal-bos-2025-01-16"}

        client = FakeClient(
            events={"nba-lal-bos-2025-01-16": [{"markets": [market()]}]},
            prices={"2": series(0.62), "1": series(0.38)})
        res = census_game(client, "nba", games[0], {}, labels, blocked=blocked)
        assert res["outcome"] == "miss"
        assert "nba-lal-bos-2025-01-16" not in client.slugs_tried
        assert any("blocked" in a for a in res["attempted"])

    def test_the_later_game_still_uses_its_own_primary_slug(self, labels):
        games = [game("g1", et_date="2025-01-15"), game("g2", et_date="2025-01-16")]
        blocked = rematch_slugs("nba", games, {})
        client = standard_client(slug="nba-lal-bos-2025-01-16",
                                 gst="2025-01-17T00:30:00Z")
        res = census_game(client, "nba", games[1], {}, labels, blocked=blocked)
        assert res["outcome"] == "priced"

    def test_a_non_rematch_schedule_blocks_nothing(self):
        games = [game("g1", et_date="2025-01-15"),
                 game("g2", et_date="2025-01-16", away="bos", home="lal")]
        assert rematch_slugs("nba", games, {}) == {}

    def test_the_block_is_computed_on_slug_abbreviations(self):
        games = [game("g1", et_date="2025-01-15"), game("g2", et_date="2025-01-16")]
        assert rematch_slugs("nhl", games, {"lal": "las"})["g1"] == \
            "nhl-las-bos-2025-01-16"


class TestRunCensus:
    @pytest.fixture
    def rig(self):
        store = Store()
        tel = Telemetry(None, "test-run", {})
        yield store, tel
        store.close()

    def test_a_full_pass_balances_and_records_the_schedule(self, rig, labels):
        store, tel = rig
        games = [game("g1"), game("g2", away="lal", home="bos")]
        counts = run_census(standard_client(), store, tel, "nba", "2024-25",
                            games, {})
        assert counts["priced"] == 2
        assert store.assert_reconciled("nba", "2024-25")["balanced"]

    def test_a_resumed_run_skips_settled_games_and_refetches_nothing(self, rig, labels):
        store, tel = rig
        games = [game("g1")]
        client = standard_client()
        run_census(client, store, tel, "nba", "2024-25", games, {})
        tried = len(client.slugs_tried)
        run_census(client, store, tel, "nba", "2024-25", games, {})
        assert len(client.slugs_tried) == tried, "resume re-fetched a settled game"

    def test_resume_is_digest_stable(self, rig):
        store, tel = rig
        games = [game("g1"), game("g2")]
        run_census(standard_client(), store, tel, "nba", "2024-25", games, {})
        first = store.digest()
        run_census(standard_client(), store, tel, "nba", "2024-25", games, {},
                   resume=False)
        assert store.digest() == first

    def test_the_limit_slice_spreads_across_the_season(self, rig):
        store, tel = rig
        games = [game(f"g{i}", et_date=f"2025-01-{(i % 28) + 1:02d}") for i in range(40)]
        run_census(FakeClient(), store, tel, "nba", "2024-25", games, {}, limit=4)
        settled = sorted(store.settled_game_ids("nba", "2024-25"))
        assert settled == ["g0", "g10", "g20", "g30"]


class TestReprobe:
    def test_a_recovered_miss_becomes_priced_and_leaves_the_misses_table(self):
        store, tel = Store(), Telemetry(None, "t", {})
        games = [game("g1")]
        empty = FakeClient()
        run_census(empty, store, tel, "nba", "2024-25", games, {})
        assert store.miss_reasons("nba", "2024-25") == {"no_market": 1}

        live = standard_client()
        out = reprobe_misses(live, store, tel, "nba", "2024-25", games, {})
        assert out == {"reprobed": 1, "recovered": 1, "still_missing": 0,
                       "not_in_schedule": 0}
        assert store.miss_reasons("nba", "2024-25") == {}
        assert store.reconcile("nba", "2024-25")["priced"] == 1
        assert live.bypassed, "the re-probe must bypass the cache"
        store.close()

    def test_a_real_miss_survives_the_reprobe(self):
        store, tel = Store(), Telemetry(None, "t", {})
        games = [game("g1")]
        run_census(FakeClient(), store, tel, "nba", "2024-25", games, {})
        out = reprobe_misses(FakeClient(), store, tel, "nba", "2024-25", games, {})
        assert out["still_missing"] == 1
        assert store.assert_reconciled("nba", "2024-25")["balanced"]
        store.close()

    def test_a_miss_whose_game_left_the_schedule_is_counted_not_swallowed(self):
        """E6's second pass quietly not running must not look like it ran clean."""
        store, tel = Store(), Telemetry(None, "t", {})
        games = [game("g1")]
        run_census(FakeClient(), store, tel, "nba", "2024-25", games, {})
        out = reprobe_misses(FakeClient(), store, tel, "nba", "2024-25", [], {})
        assert out["not_in_schedule"] == 1 and out["reprobed"] == 0
        store.close()

    def test_an_empty_reason_tuple_is_refused_rather_than_building_invalid_sql(self):
        store, tel = Store(), Telemetry(None, "t", {})
        with pytest.raises(ValueError, match="non-empty"):
            reprobe_misses(FakeClient(), store, tel, "nba", "2024-25", [], {},
                           reasons=())
        store.close()

    def test_reasons_other_than_no_market_are_not_reprobed(self):
        store, tel = Store(), Telemetry(None, "t", {})
        games = [game("g1")]
        run_census(standard_client(prices=("0.5", "0.5")), store, tel,
                   "nba", "2024-25", games, {})
        out = reprobe_misses(standard_client(), store, tel, "nba", "2024-25", games, {})
        assert out["reprobed"] == 0
        store.close()


class TestTipoffHelper:
    @pytest.mark.parametrize("gst,et_date,ok", [
        ("2025-01-16T00:30:00Z", "2025-01-15", True),
        ("2025-01-16T05:57:00Z", "2025-01-15", False),   # 00:57 ET next day
        ("2025-01-15T14:00:00Z", "2025-01-15", False),   # 09:00 ET
        ("2025-01-15 19:30:00", "2025-01-15", False),    # naive
        (None, "2025-01-15", False),
        ("not-a-date", "2025-01-15", False),
    ])
    def test_plausibility(self, gst, et_date, ok):
        assert tipoff_is_plausible(gst, et_date)[0] is ok

    def test_a_rejection_says_why(self):
        assert "ET hour" in tipoff_is_plausible("2025-01-15T14:00:00Z", "2025-01-15")[1]


class TestSliceGames:
    def test_head_takes_the_earliest(self):
        games = [game(f"g{i}") for i in range(10)]
        assert [g["game_id"] for g in slice_games(games, 3, "head")] == ["g0", "g1", "g2"]

    def test_stride_covers_the_whole_range(self):
        games = [game(f"g{i}") for i in range(10)]
        assert [g["game_id"] for g in slice_games(games, 3)] == ["g0", "g3", "g6"]

    def test_no_limit_returns_everything(self):
        games = [game(f"g{i}") for i in range(10)]
        assert len(slice_games(games, None)) == 10
        assert len(slice_games(games, 99)) == 10

    def test_an_unknown_strategy_is_refused(self):
        games = [game(f"g{i}") for i in range(5)]
        with pytest.raises(ValueError, match="unknown slice strategy"):
            slice_games(games, 2, "vibes")

    @pytest.mark.parametrize("n,limit", [(5, 3), (7, 4), (1312, 200), (1230, 200)])
    def test_stride_never_repeats_a_game(self, n, limit):
        """Previously called slice_games(games, 5) on 5 games, which returns early
        on `limit >= len(games)` and never reached the stride branch at all."""
        games = [game(f"g{i:05d}") for i in range(n)]
        picked = slice_games(games, limit)
        assert len({g["game_id"] for g in picked}) == len(picked)
        assert len(picked) == limit

    def test_stride_spans_the_whole_list(self):
        games = [game(f"g{i:05d}") for i in range(1000)]
        picked = slice_games(games, 10)
        assert picked[0]["game_id"] == "g00000"
        assert picked[-1]["game_id"] == "g00900"


class TestVolumeParsing:
    """Which key wins decides the liquidity tier a game lands in."""

    @pytest.mark.parametrize("mkt,want", [
        ({"volumeNum": 5.0, "volume": "9"}, 5.0),     # volumeNum is preferred
        ({"volume": "1900000"}, 1900000.0),           # the string form Gamma sends
        ({"volumeNum": "n/a", "volume": 7}, 7.0),     # unparseable falls through
        ({"volume": None}, None),
        ({}, None),
    ])
    def test_volume_parsing(self, mkt, want):
        from chira.census import _volume
        assert _volume(mkt) == want


class TestAbbrMapLoading:
    def test_an_unresolved_team_refuses_to_load(self, tmp_path):
        """A partial map books every game of the missing team as `no_market`."""
        p = tmp_path / "m.json"
        p.write_text(json.dumps({"seasons": {"2024-25": {"nhl": {
            "map": {"bos": "bos"}, "unresolved": ["vgk"]}}}}))
        with pytest.raises(ValueError, match="unresolved teams"):
            load_abbr_map(str(p), "2024-25", "nhl")

    def test_a_missing_sport_season_refuses_to_load(self, tmp_path):
        p = tmp_path / "m.json"
        p.write_text(json.dumps({"seasons": {}}))
        with pytest.raises(KeyError):
            load_abbr_map(str(p), "2024-25", "nhl")

    def test_a_resolved_map_loads(self, tmp_path):
        p = tmp_path / "m.json"
        p.write_text(json.dumps({"seasons": {"2024-25": {"nhl": {
            "map": {"vgk": "las"}, "unresolved": []}}}}))
        assert load_abbr_map(str(p), "2024-25", "nhl") == {"vgk": "las"}


class TestManifest:
    def test_it_records_the_window_and_the_map_fingerprint(self):
        m = manifest("nba", "2024-25",
                     [game("g1", et_date="2024-10-22"), game("g2", et_date="2025-04-13")],
                     {"vgk": "las", "bos": "bos"})
        assert m["date_window"] == ["2024-10-22", "2025-04-13"]
        assert m["abbr_map_irregulars"] == {"vgk": "las"}
        assert len(m["abbr_map_fingerprint"]) == 16

    def test_the_fingerprint_changes_when_the_map_changes(self):
        a = manifest("nba", "2024-25", [game()], {"vgk": "las"})
        b = manifest("nba", "2024-25", [game()], {"vgk": "vgk"})
        assert a["abbr_map_fingerprint"] != b["abbr_map_fingerprint"]
