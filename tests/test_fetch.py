"""Tests for fetch.py: the local disk cache (load_cache/save_cache) --
corruption recovery on load and atomic, non-interleaving writes on save
(see https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/7)
-- fetch_pages_content_and_categories's per-batch progress output
(see https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/9)
-- and cache age detection plus fetch_all_with_cache's overwrite_cache
option (see https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/20)."""

import glob
import json
import os
import time

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


# ---------------------------------------------------------------------
# cache_age_days (issue #20)
# ---------------------------------------------------------------------


def test_cache_age_days_returns_none_when_file_absent(cache_file):
    assert fetch.cache_age_days() is None


def test_cache_age_days_reflects_modification_time(cache_file):
    fetch.save_cache({"a": 1})
    thirty_five_days_ago = time.time() - 35 * 86400
    os.utime(cache_file, (thirty_five_days_ago, thirty_five_days_ago))

    age = fetch.cache_age_days()

    assert age is not None
    assert 34.9 < age < 35.1


def test_cache_age_days_near_zero_for_freshly_saved_cache(cache_file):
    fetch.save_cache({"a": 1})
    age = fetch.cache_age_days()
    assert age is not None
    assert age < 0.01


# ---------------------------------------------------------------------
# fetch_all_with_cache (issue #20: overwrite_cache)
# ---------------------------------------------------------------------


def _fake_fetch_pages(calls: list[list[str]]):
    """Stand-in for fetch_pages_content_and_categories: records the
    titles it was asked to fetch and returns placeholder content for
    each, so tests can assert exactly what fetch_all_with_cache decided
    was "missing" without any real network access."""

    def _fake(session, titles):
        calls.append(list(titles))
        return {
            t: {"wikitext": f"fresh wikitext for {t}", "categories": []} for t in titles
        }

    return _fake


def test_fetch_all_with_cache_only_fetches_missing_titles(monkeypatch, cache_file):
    fetch.save_cache({"Cached Athlete": {"wikitext": "old", "categories": []}})
    calls: list[list[str]] = []
    monkeypatch.setattr(
        fetch, "fetch_pages_content_and_categories", _fake_fetch_pages(calls)
    )

    result = fetch.fetch_all_with_cache(
        object(), ["Cached Athlete", "New Athlete"], use_cache=True
    )

    assert calls == [["New Athlete"]]
    assert result["Cached Athlete"]["wikitext"] == "old"
    assert result["New Athlete"]["wikitext"] == "fresh wikitext for New Athlete"


def test_fetch_all_with_cache_overwrite_cache_refetches_everything(
    monkeypatch, cache_file
):
    fetch.save_cache({"Cached Athlete": {"wikitext": "old", "categories": []}})
    calls: list[list[str]] = []
    monkeypatch.setattr(
        fetch, "fetch_pages_content_and_categories", _fake_fetch_pages(calls)
    )

    result = fetch.fetch_all_with_cache(
        object(), ["Cached Athlete"], use_cache=True, overwrite_cache=True
    )

    assert calls == [["Cached Athlete"]]
    assert result["Cached Athlete"]["wikitext"] == "fresh wikitext for Cached Athlete"


def test_fetch_all_with_cache_overwrite_cache_saves_refreshed_entries(
    monkeypatch, cache_file
):
    fetch.save_cache({"Cached Athlete": {"wikitext": "old", "categories": []}})
    monkeypatch.setattr(
        fetch, "fetch_pages_content_and_categories", _fake_fetch_pages([])
    )

    fetch.fetch_all_with_cache(
        object(), ["Cached Athlete"], use_cache=True, overwrite_cache=True
    )

    assert (
        fetch.load_cache()["Cached Athlete"]["wikitext"]
        == "fresh wikitext for Cached Athlete"
    )


def test_fetch_all_with_cache_overwrite_cache_preserves_untouched_entries(
    monkeypatch, cache_file
):
    """A --limit run with --overwrite-cache must not drop cache entries
    for articles outside the current scan -- only the titles actually
    requested this run should be refreshed."""
    fetch.save_cache(
        {
            "Cached Athlete": {"wikitext": "old", "categories": []},
            "Untouched Athlete": {"wikitext": "keep me", "categories": []},
        }
    )
    monkeypatch.setattr(
        fetch, "fetch_pages_content_and_categories", _fake_fetch_pages([])
    )

    fetch.fetch_all_with_cache(
        object(), ["Cached Athlete"], use_cache=True, overwrite_cache=True
    )

    assert fetch.load_cache()["Untouched Athlete"]["wikitext"] == "keep me"


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
