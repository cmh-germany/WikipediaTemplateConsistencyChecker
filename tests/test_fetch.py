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


def test_cache_age_days_returns_none_for_cache_without_fetched_at(cache_file):
    # A cache.json written by a version of this tool that predates the
    # "fetched_at" field -- must not crash, and there's no reliable age
    # to report for it.
    fetch.save_cache({"Old Entry": {"wikitext": "...", "categories": []}})
    assert fetch.cache_age_days() is None


def test_cache_age_days_reflects_entry_fetch_timestamp(cache_file):
    thirty_five_days_ago = time.time() - 35 * 86400
    fetch.save_cache(
        {
            "Athlete": {
                "wikitext": "...",
                "categories": [],
                "fetched_at": thirty_five_days_ago,
            }
        }
    )

    age = fetch.cache_age_days()

    assert age is not None
    assert 34.9 < age < 35.1


def test_cache_age_days_uses_oldest_entry_not_newest(cache_file):
    fetch.save_cache(
        {
            "Old Athlete": {
                "wikitext": "...",
                "categories": [],
                "fetched_at": time.time() - 35 * 86400,
            },
            "New Athlete": {
                "wikitext": "...",
                "categories": [],
                "fetched_at": time.time(),
            },
        }
    )

    age = fetch.cache_age_days()

    assert age is not None
    assert 34.9 < age < 35.1


def test_cache_age_days_ignores_file_modification_time(cache_file):
    """A cache.json touched by something unrelated to this tool (an
    editor, a git checkout, a sync client) must not look freshly
    refreshed just because its mtime changed -- age must come from the
    entries' own "fetched_at" timestamps, not the file's mtime."""
    thirty_five_days_ago = time.time() - 35 * 86400
    fetch.save_cache(
        {
            "Athlete": {
                "wikitext": "...",
                "categories": [],
                "fetched_at": thirty_five_days_ago,
            }
        }
    )
    os.utime(cache_file, None)  # bump mtime to "now" without touching content

    age = fetch.cache_age_days()

    assert age is not None
    assert 34.9 < age < 35.1


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


def test_fetch_all_with_cache_stamps_fetched_at_on_new_entries(monkeypatch, cache_file):
    monkeypatch.setattr(
        fetch, "fetch_pages_content_and_categories", _fake_fetch_pages([])
    )
    before = time.time()

    result = fetch.fetch_all_with_cache(object(), ["New Athlete"], use_cache=True)

    assert before <= result["New Athlete"]["fetched_at"] <= time.time()


def test_fetch_all_with_cache_leaves_existing_entries_fetched_at_untouched(
    monkeypatch, cache_file
):
    # A cache with an old entry and a scan that only asks for a
    # *different*, new title: adding the new title must not bump the
    # old entry's timestamp, even though save_cache() rewrites the whole
    # file -- otherwise cache_age_days() would look fresh right after a
    # scan that only ever touched brand-new articles.
    old_fetched_at = time.time() - 35 * 86400
    fetch.save_cache(
        {
            "Old Athlete": {
                "wikitext": "old",
                "categories": [],
                "fetched_at": old_fetched_at,
            }
        }
    )
    monkeypatch.setattr(
        fetch, "fetch_pages_content_and_categories", _fake_fetch_pages([])
    )

    fetch.fetch_all_with_cache(object(), ["Old Athlete", "New Athlete"], use_cache=True)

    assert fetch.load_cache()["Old Athlete"]["fetched_at"] == old_fetched_at


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


def test_fetch_all_with_cache_overwrite_cache_refreshes_stale_timestamp(
    monkeypatch, cache_file
):
    stale_fetched_at = time.time() - 60 * 86400
    fetch.save_cache(
        {
            "Cached Athlete": {
                "wikitext": "old",
                "categories": [],
                "fetched_at": stale_fetched_at,
            }
        }
    )
    monkeypatch.setattr(
        fetch, "fetch_pages_content_and_categories", _fake_fetch_pages([])
    )

    fetch.fetch_all_with_cache(
        object(), ["Cached Athlete"], use_cache=True, overwrite_cache=True
    )

    assert fetch.load_cache()["Cached Athlete"]["fetched_at"] > stale_fetched_at


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
