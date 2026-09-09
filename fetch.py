"""Access to the German Wikipedia via the MediaWiki API.

Fetches the list of articles that embed "Vorlage:Infobox Leichtathlet"
(the athlete infobox template) plus their wikitext and categories.
Results are cached locally in a JSON file so a repeated scan doesn't
have to reload every article each time.
"""

import json
import os
import sys
import tempfile
import time
from typing import Any

import requests

API_URL = "https://de.wikipedia.org/w/api.php"

# Wikipedia's policy requires a descriptive User-Agent with a way to
# contact the maintainer. Adjust as needed.
USER_AGENT = "WikipediaTemplateChecker/1.0 (local consistency checker; no bot flag)"

# Real page title on German Wikipedia -- do not translate.
TEMPLATE_NAME = "Vorlage:Infobox Leichtathlet"

CACHE_FILE = os.path.join(os.path.dirname(__file__), "cache.json")

# Age at which cache.json is considered stale enough to warn about (see
# cache_age_days()).
CACHE_STALE_AGE_DAYS = 30

# Short delay between batch requests to avoid overloading the API.
REQUEST_DELAY_SECONDS = 0.5

# Titles per API call when fetching wikitext/categories.
BATCH_SIZE = 50

MAX_RETRIES = 5


def get_session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _get_with_retry(session, params):
    """GET with backoff on 429 (Too Many Requests) / 5xx errors."""
    delay = 2.0
    for attempt in range(MAX_RETRIES):
        response = session.get(API_URL, params=params, timeout=30)
        if response.status_code == 429 or response.status_code >= 500:
            retry_after = response.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else delay
            if attempt == MAX_RETRIES - 1:
                response.raise_for_status()
            time.sleep(wait)
            delay *= 2
            continue
        response.raise_for_status()
        return response
    response.raise_for_status()
    return response


def _api_query(session, params, stop_when=None):
    """Runs an API query and automatically follows MediaWiki
    continuation. Returns the merged 'query' object.

    stop_when(merged) -> bool can be passed to abort continuation early
    (e.g. once enough titles have been collected)."""
    params = dict(params)
    params["format"] = "json"
    params["formatversion"] = "2"

    merged: dict[str, Any] = {}
    while True:
        response = _get_with_retry(session, params)
        data = response.json()

        if "error" in data:
            raise RuntimeError(f"MediaWiki API error: {data['error']}")

        _merge_query(merged, data.get("query", {}))

        if stop_when and stop_when(merged):
            break

        if "continue" in data:
            params.update(data["continue"])
            time.sleep(REQUEST_DELAY_SECONDS)
        else:
            break

    return merged


def _merge_page(existing, page):
    """Merges one 'pages' entry from a continuation batch into the
    already-collected entry for the same title: list-valued fields
    (e.g. 'categories') are extended, everything else is overwritten."""
    for pkey, pval in page.items():
        if isinstance(pval, list):
            existing.setdefault(pkey, [])
            existing[pkey].extend(pval)
        else:
            existing[pkey] = pval


def _merge_query(merged, query):
    for key, value in query.items():
        if key != "pages":
            # e.g. 'embeddedin': extend the list
            merged.setdefault(key, [])
            merged[key].extend(value)
            continue

        merged.setdefault("pages", {})
        for page in value:
            title = page.get("title")
            existing = merged["pages"].setdefault(title, page)
            if existing is not page:
                _merge_page(existing, page)


def list_pages_using_template(session, template_name=TEMPLATE_NAME, limit=None):
    """Returns all article titles (namespace 0) that embed the template."""
    params = {
        "action": "query",
        "list": "embeddedin",
        "eititle": template_name,
        "einamespace": 0,
        "eilimit": "max" if not limit else min(limit, 500),
    }
    stop_when = (
        (lambda merged: len(merged.get("embeddedin", [])) >= limit) if limit else None
    )
    query = _api_query(session, params, stop_when=stop_when)
    titles = [p["title"] for p in query.get("embeddedin", [])]
    if limit:
        titles = titles[:limit]
    return titles


def fetch_pages_content_and_categories(session, titles):
    """Fetches the current wikitext and categories for a list of titles.
    Prints one progress line per batch ("{done}/{total} articles
    fetched") so a large --scan run shows visible activity instead of
    appearing to hang during its several-minutes-long, deliberately
    throttled fetch loop. Returns {title: {"wikitext": str,
    "categories": [str]}}."""
    result = {}
    total = len(titles)
    done = 0
    for i in range(0, len(titles), BATCH_SIZE):
        batch = titles[i : i + BATCH_SIZE]
        params = {
            "action": "query",
            "titles": "|".join(batch),
            "prop": "revisions|categories",
            "rvprop": "content",
            "rvslots": "main",
            "cllimit": "max",
        }
        query = _api_query(session, params)
        for title, page in query.get("pages", {}).items():
            if page.get("missing"):
                continue
            revisions = page.get("revisions", [])
            if not revisions:
                continue
            wikitext = revisions[0]["slots"]["main"]["content"]
            categories = [c["title"] for c in page.get("categories", [])]
            result[title] = {"wikitext": wikitext, "categories": categories}
        done += len(batch)
        print(f"{done}/{total} articles fetched")
        time.sleep(REQUEST_DELAY_SECONDS)
    return result


def templates_exist(session, template_titles):
    """Checks, for a list of template titles (e.g. 'Vorlage:GER'), whether
    the page exists. Returns {title: bool}. Mirrors the {{#ifexist:}}
    check that the infobox itself performs for the 'nation' field."""
    unique_titles = sorted(set(template_titles))
    exists = {}
    for i in range(0, len(unique_titles), BATCH_SIZE):
        batch = unique_titles[i : i + BATCH_SIZE]
        params = {
            "action": "query",
            "titles": "|".join(batch),
        }
        query = _api_query(session, params)
        for title, page in query.get("pages", {}).items():
            exists[title] = not page.get("missing", False)
        time.sleep(REQUEST_DELAY_SECONDS)
    return exists


def load_cache():
    """Loads cache.json, if present. A cache file that isn't valid JSON --
    e.g. left over from a crash mid-write on an older version of this tool,
    or from two scans that ran concurrently against the same directory --
    is treated as absent rather than raised, so a corrupted cache can't
    permanently block every future run; the next successful save_cache()
    overwrites it with well-formed data."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"Warning: cache.json is corrupted ({exc}) -- ignoring it and "
            "starting with an empty cache. It will be overwritten on the "
            "next successful fetch.",
            file=sys.stderr,
        )
        return {}


def cache_age_days() -> float | None:
    """Returns how many days ago the oldest entry in the cache was
    fetched, or None if the cache is empty/absent, or none of its
    entries carry a "fetched_at" timestamp (a cache.json written by a
    version of this tool that predates this field).

    Deliberately does *not* use cache.json's filesystem modification
    time: fetch_all_with_cache() rewrites the whole file (via
    save_cache()) whenever even a single new title needs fetching, so a
    handful of newly-published articles would reset the file's mtime to
    "now" while thousands of untouched entries are still months old --
    the file would look fresh when almost none of its data is. mtime
    also isn't a signal this tool controls: a git checkout, an editor,
    or a sync client touching the file wouldn't mean the underlying
    Wikipedia data was actually refreshed. Each entry's own
    "fetched_at", stamped only when that specific title is (re)fetched,
    doesn't have either problem."""
    cache = load_cache()
    fetch_times = [
        entry["fetched_at"]
        for entry in cache.values()
        if isinstance(entry, dict) and "fetched_at" in entry
    ]
    if not fetch_times:
        return None
    return (time.time() - min(fetch_times)) / 86400


def save_cache(cache):
    """Writes cache.json atomically: the new content is written to a
    temporary file in the same directory and then moved into place with
    os.replace(), which is atomic on both POSIX and Windows. This prevents
    two concurrently running scans from interleaving their writes into a
    single corrupted file -- each save fully succeeds or fully fails, and
    the last one to finish wins."""
    cache_dir = os.path.dirname(CACHE_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(
        dir=cache_dir, prefix=os.path.basename(CACHE_FILE) + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
        os.replace(tmp_path, CACHE_FILE)
    except BaseException:
        os.remove(tmp_path)
        raise


def fetch_all_with_cache(session, titles, use_cache=True, overwrite_cache=False):
    """Like fetch_pages_content_and_categories, but uses a local cache
    for articles already fetched before (keyed by title, without a
    revision check -- delete cache.json, or pass overwrite_cache=True, to
    force a full refresh). overwrite_cache=True re-fetches every title in
    `titles` from Wikipedia regardless of what's already cached for it,
    then writes the fresh results back into the cache -- unlike
    use_cache=False, which also skips the cache but never saves to it.
    Every freshly (re)fetched entry is stamped with a "fetched_at" epoch
    timestamp (see cache_age_days()); entries reused from the existing
    cache keep whatever timestamp they already had."""
    cache = load_cache() if use_cache else {}
    missing = list(titles) if overwrite_cache else [t for t in titles if t not in cache]

    if missing:
        fresh = fetch_pages_content_and_categories(session, missing)
        fetched_at = time.time()
        for entry in fresh.values():
            entry["fetched_at"] = fetched_at
        cache.update(fresh)
        if use_cache:
            save_cache(cache)

    return {t: cache[t] for t in titles if t in cache}
