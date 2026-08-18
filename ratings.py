"""Film metadata (IMDb rating, English plot, cast, director) via the OMDb
API (omdbapi.com).

Deliberately not scraping IMDb directly: it's against their terms of
service and defended by aggressive anti-bot measures. OMDb is a free
third-party API built for exactly this lookup (title -> IMDb data),
and its Plot/Actors/Director fields come back in English regardless of
what language the source cinema's own site returned (Pathé, Cineville and
Vue are all Dutch sites -- their native descriptions are in Dutch).

Requires a free API key (config.yaml: omdb_api_key, from
https://www.omdbapi.com/apikey.aspx). If unset, get_ratings() returns an
empty dict and the feature is silently skipped -- nothing else breaks.

Known gap: OMDb's `y` (year) parameter does an exact match, so a wrong or
approximate year (see film_year extraction in each source module) can cause
a real film to come back "not found" rather than falling back to a
title-only match. Rare in practice for mainstream new releases, more likely
for older revival/re-release screenings. Worst case: that film just keeps
its native (Dutch) description/cast/director and no rating.

Results are cached to disk (ratings_cache.json, gitignored) keyed by
"title|year" -- the same film plays at many cinemas across many days, and
this keeps repeat runs fast and well under OMDb's free-tier limit
(1000 lookups/day).
"""

import json
import re
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).parent / "ratings_cache.json"
API_URL = "http://www.omdbapi.com/"

# Suffixes seen in Cineville/Pathé/Vue listings that break exact-title
# matching against OMDb (re-releases, version/format tags).
_TITLE_SUFFIX_RE = re.compile(
    r"\s*[\(\[](re-?release|restored|remastered|ov|originele versie|4k|anniversary edition)[\)\]]\s*$",
    re.IGNORECASE,
)


def _clean_title(title: str) -> str:
    return _TITLE_SUFFIX_RE.sub("", title).strip()


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=1, sort_keys=True))


def _cached(cache: dict, key: str):
    """A cache hit is either None (confirmed no match) or a dict (the new
    schema). A bare float means it's a value from before this file tracked
    plot/cast/director -- treat as a miss so it gets refetched once.

    A dict without an "imdb_id" key predates the IMDb-link/full-plot change,
    so it's also a miss: refetching once picks up the id and the longer
    Plot. Confirmed misses (None) stay cached -- there's nothing new to
    learn about a film OMDb doesn't have."""
    if key not in cache:
        return False, None
    value = cache[key]
    if value is None:
        return True, None
    if isinstance(value, dict) and "imdb_id" in value:
        return True, value
    return False, None


# Errors OMDb returns that mean "this key/request is broken", not "this
# film wasn't found" -- these must never be cached (a bad key would
# otherwise permanently poison every title as "no rating"), and are worth
# aborting the whole batch for rather than burning through every remaining
# lookup one at a time.
_FATAL_ERRORS = {"invalid api key!", "no api key provided.", "request limit reached!"}


def _clean_field(value) -> str | None:
    return value if value and value != "N/A" else None


def _cap_csv(value: str | None, limit: int) -> str | None:
    """OMDb's Genre often lists 3+ comma-separated values -- too crowded
    next to a film title. Keep just the first `limit`."""
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return ", ".join(parts[:limit]) or None


def _lookup(session: requests.Session, title: str, year: str | None, api_key: str):
    """Returns (data_or_None, cacheable: bool, fatal_error: str | None).
    data, when present, is {"rating": float|None, "imdb_id": str|None,
    "plot": str|None, "cast": str|None, "director": str|None,
    "genre": str|None}."""
    # plot=full: OMDb's default "short" plot is a single sentence, which is
    # all the by-cinema rows need but leaves the expandable synopsis in the
    # movie gallery with nothing to expand into.
    params = {"apikey": api_key, "t": title, "type": "movie", "plot": "full"}
    if year:
        params["y"] = year
    try:
        resp = session.get(API_URL, params=params, timeout=10)
        # Don't raise_for_status(): OMDb returns its error detail as a JSON
        # body (Response/Error) even on non-2xx statuses (e.g. 401 for an
        # invalid key) -- we need that body to tell a bad key apart from a
        # genuine "not found".
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None, False, None  # transient (network/parse) failure -- retry later, don't cache

    if data.get("Response") != "True":
        error = (data.get("Error") or "").strip()
        if error.lower() in _FATAL_ERRORS:
            return None, False, error
        return None, True, None  # genuine "not found" -- safe to cache

    rating = None
    raw_rating = data.get("imdbRating")
    if raw_rating and raw_rating != "N/A":
        try:
            rating = float(raw_rating)
        except ValueError:
            pass

    result = {
        "rating": rating,
        "imdb_id": _clean_field(data.get("imdbID")),
        "plot": _clean_field(data.get("Plot")),
        "cast": _clean_field(data.get("Actors")),
        "director": _clean_field(data.get("Director")),
        "genre": _cap_csv(data.get("Genre"), 2),
    }
    return result, True, None


def get_ratings(title_years: set[tuple[str, str | None]], api_key: str) -> dict[tuple[str, str | None], dict]:
    """title_years: set of (film_title, film_year_or_None) as they appear in
    our records. Returns a dict from that same key to
    {"rating": float|None, "imdb_id": str|None, "plot": str|None,
    "cast": str|None, "director": str|None, "genre": str|None}, omitting
    entries with no OMDb match at all."""
    if not api_key:
        return {}

    cache = _load_cache()
    session = requests.Session()
    results = {}
    dirty = False

    for title, year in title_years:
        cache_key = f"{_clean_title(title)}|{year or ''}"
        hit, data = _cached(cache, cache_key)
        if not hit:
            data, cacheable, fatal = _lookup(session, _clean_title(title), year, api_key)
            if fatal:
                print(f"[ratings] OMDb error: {fatal} -- stopping, check omdb_api_key in config.yaml")
                break
            if cacheable:
                cache[cache_key] = data
                dirty = True
        if data is not None:
            results[(title, year)] = data

    if dirty:
        _save_cache(cache)
    return results
