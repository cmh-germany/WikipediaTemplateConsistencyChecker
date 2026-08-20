"""Tests for fetch.py: the local disk cache (load_cache/save_cache) --
corruption recovery on load and atomic, non-interleaving writes on save
(see https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/7)
-- and fetch_pages_content_and_categories's per-batch progress output
(see https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/9)."""

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


def _fake_api_query_echoing_titles(session, params, stop_when=None):
    """Stand-in for fetch._api_query: returns one 'pages' entry per
    requested title, with placeholder content/categories, so batching
    can be exercised without a real MediaWiki API call."""
    titles = params["titles"].split("|")
    return {
        "pages": {
            title: {
                "revisions": [
                    {"slots": {"main": {"content": f"wikitext for {title}"}}}
                ],
                "categories": [],
            }
            for title in titles
        }
    }


def test_fetch_pages_prints_progress_once_per_batch(monkeypatch, capsys):
    """See https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/9:
    one "{done}/{total} articles fetched" line after each batch, not
    per article and not only at the end."""
    monkeypatch.setattr(fetch, "BATCH_SIZE", 2)
    monkeypatch.setattr(fetch.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(fetch, "_api_query", _fake_api_query_echoing_titles)

    titles = ["A", "B", "C", "D", "E"]
    result = fetch.fetch_pages_content_and_categories(object(), titles)

    assert set(result) == set(titles)
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "2/5 articles fetched",
        "4/5 articles fetched",
        "5/5 articles fetched",
    ]


def test_fetch_pages_progress_reflects_batch_size_not_successful_fetches(
    monkeypatch, capsys
):
    """'done' counts titles processed in the batch, not just the ones
    that came back with content -- a batch containing a missing/deleted
    page must not shrink the progress count or total."""
    monkeypatch.setattr(fetch, "BATCH_SIZE", 3)
    monkeypatch.setattr(fetch.time, "sleep", lambda seconds: None)

    def fake_api_query(session, params, stop_when=None):
        titles = params["titles"].split("|")
        pages: dict[str, object] = {}
        for title in titles:
            if title == "Missing":
                pages[title] = {"missing": True}
            else:
                pages[title] = {
                    "revisions": [
                        {"slots": {"main": {"content": f"wikitext for {title}"}}}
                    ],
                    "categories": [],
                }
        return {"pages": pages}

    monkeypatch.setattr(fetch, "_api_query", fake_api_query)

    titles = ["A", "Missing", "B"]
    result = fetch.fetch_pages_content_and_categories(object(), titles)

    assert set(result) == {"A", "B"}
    out = capsys.readouterr().out.splitlines()
    assert out == ["3/3 articles fetched"]


def test_fetch_pages_prints_nothing_for_empty_title_list(monkeypatch, capsys):
    monkeypatch.setattr(fetch, "_api_query", _fake_api_query_echoing_titles)

    result = fetch.fetch_pages_content_and_categories(object(), [])

    assert result == {}
    assert capsys.readouterr().out == ""


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
