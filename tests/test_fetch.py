"""Tests for fetch.py's local disk cache (load_cache/save_cache):
corruption recovery on load and atomic, non-interleaving writes on save.
See https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/7."""

import glob
import json
import os

import pytest

import fetch


@pytest.fixture
def cache_file(tmp_path, monkeypatch):
    """Points fetch.CACHE_FILE at a throwaway path for the duration of
    the test, so tests don't touch the real cache.json."""
    path = os.path.join(tmp_path, "cache.json")
    monkeypatch.setattr(fetch, "CACHE_FILE", path)
    return path


def test_load_cache_returns_empty_dict_when_file_absent(cache_file):
    assert fetch.load_cache() == {}


def test_save_then_load_round_trips(cache_file):
    data = {"Usain Bolt": {"wikitext": "...", "categories": ["Leichtathlet"]}}
    fetch.save_cache(data)
    assert fetch.load_cache() == data


def test_load_cache_recovers_from_corrupted_json(cache_file, capsys):
    """A cache.json left interleaved by two concurrent writers (or
    otherwise truncated/malformed) must not crash every future run --
    it should be treated as an empty cache, with a warning on stderr."""
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write('{"Usain Bolt": {"wikitext": "a"}}\n{"Jesse Owens":')

    assert fetch.load_cache() == {}
    assert "corrupted" in capsys.readouterr().err.lower()


def test_save_cache_does_not_leave_temp_files_behind(cache_file):
    fetch.save_cache({"a": 1})
    leftovers = glob.glob(cache_file + ".*.tmp")
    assert leftovers == []


def test_save_cache_is_atomic_and_leaves_valid_json_on_repeated_writes(cache_file):
    """Simulates what two concurrently running scans do: each calls
    save_cache with its own view of the cache. Every intermediate state
    on disk must be fully valid JSON -- never a half-written or
    interleaved mix of two writes -- which os.replace() guarantees."""
    for i in range(20):
        fetch.save_cache({"key": i})
        with open(cache_file, encoding="utf-8") as f:
            # Must parse cleanly at every step; a naive open(..., "w")
            # + json.dump() would risk a reader observing a truncated
            # or interleaved file here under concurrent writers.
            assert json.load(f)["key"] == i
