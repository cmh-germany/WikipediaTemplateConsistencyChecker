"""Access to the German Wikipedia via the MediaWiki API.

Fetches the list of articles that embed "Vorlage:Infobox Leichtathlet"
(the athlete infobox template) plus their wikitext and categories.
Results are cached locally in a JSON file so a repeated scan doesn't
have to reload every article each time.
"""

import json
import os
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
    Returns {title: {"wikitext": str, "categories": [str]}}."""
    result = {}
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
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def fetch_all_with_cache(session, titles, use_cache=True):
    """Like fetch_pages_content_and_categories, but uses a local cache
    for articles already fetched before (keyed by title, without a
    revision check -- delete cache.json to force a full refresh)."""
    cache = load_cache() if use_cache else {}
    missing = [t for t in titles if t not in cache]

    if missing:
        fresh = fetch_pages_content_and_categories(session, missing)
        cache.update(fresh)
        if use_cache:
            save_cache(cache)

    return {t: cache[t] for t in titles if t in cache}
