"""Tests for the on-disk cache.

The cache is the component most able to do quiet damage: everything it gets
wrong looks like data. Three failure modes are specifically covered here --
serving a payload written under a different abbreviation map, surviving a
truncated entry, and never writing an empty result (that last one is enforced
in http.validate_*, tested in test_http.py).
"""

from __future__ import annotations

import json

import pytest

from chira.cache import Cache, fingerprint


@pytest.fixture
def cache(tmp_path):
    return Cache(tmp_path / "c", abbr_version="v1")


class TestFingerprint:
    def test_key_order_does_not_change_the_fingerprint(self):
        assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})

    def test_different_content_changes_it(self):
        assert fingerprint({"a": 1}) != fingerprint({"a": 2})

    def test_it_is_short_enough_to_read_in_a_manifest(self):
        assert len(fingerprint({"a": 1})) == 16


class TestRoundTrip:
    def test_a_miss_returns_none_and_is_counted(self, cache):
        assert cache.get("https://x/1") is None
        assert cache.stats["miss"] == 1

    def test_put_then_get_returns_the_payload(self, cache):
        cache.put("https://x/1", [{"a": 1}])
        assert cache.get("https://x/1") == [{"a": 1}]
        assert cache.stats["hit"] == 1

    def test_entries_are_sharded_not_all_in_one_directory(self, cache):
        cache.put("https://x/1", [1])
        path = cache.path("https://x/1")
        assert path.parent.name == cache.key("https://x/1")[:2]

    def test_the_entry_records_what_it_was_keyed_by(self, cache):
        cache.put("https://x/1", [1])
        entry = json.loads(cache.path("https://x/1").read_text())
        assert entry["url"] == "https://x/1"
        assert entry["abbr_version"] == "v1"
        assert entry["schema_version"] == cache.schema_version


class TestInvalidation:
    def test_a_different_abbr_map_does_not_see_the_old_entry(self, tmp_path):
        """The abbreviation map is an input to every slug.

        Without this, correcting `vgk` to `las` would leave 164 cached
        "no market" answers computed under the old, wrong map.
        """
        a = Cache(tmp_path / "c", abbr_version="v1")
        a.put("https://x/1", ["old"])
        b = Cache(tmp_path / "c", abbr_version="v2")
        assert b.get("https://x/1") is None

    def test_a_different_schema_version_does_not_see_the_old_entry(self, tmp_path):
        a = Cache(tmp_path / "c", abbr_version="v1", schema_version=1)
        a.put("https://x/1", ["old"])
        b = Cache(tmp_path / "c", abbr_version="v1", schema_version=2)
        assert b.get("https://x/1") is None

    def test_same_inputs_give_the_same_key_across_instances(self, tmp_path):
        a = Cache(tmp_path / "c", abbr_version="v1")
        b = Cache(tmp_path / "c", abbr_version="v1")
        a.put("https://x/1", ["shared"])
        assert b.get("https://x/1") == ["shared"]


class TestDamage:
    def test_a_truncated_entry_reads_as_a_miss_not_an_exception(self, cache):
        """A census killed mid-write must not be unresumable."""
        cache.put("https://x/1", [1])
        cache.path("https://x/1").write_text("{not json")
        assert cache.get("https://x/1") is None
        assert cache.stats["corrupt"] == 1

    def test_an_entry_whose_url_does_not_match_is_refused(self, cache):
        cache.put("https://x/1", [1])
        p = cache.path("https://x/1")
        p.write_text(json.dumps({"url": "https://x/OTHER", "payload": [1]}))
        assert cache.get("https://x/1") is None
        assert cache.stats["collision"] == 1

    def test_put_leaves_no_temp_file_behind(self, cache):
        cache.put("https://x/1", [1])
        leftovers = list(cache.path("https://x/1").parent.glob("*.tmp"))
        assert leftovers == []

    def test_a_failed_write_does_not_leave_a_partial_entry(self, cache, monkeypatch):
        class Unserializable:
            pass

        with pytest.raises(TypeError):
            cache.put("https://x/1", Unserializable())
        assert cache.get("https://x/1") is None
        assert list(cache.path("https://x/1").parent.glob("*.tmp")) == []
