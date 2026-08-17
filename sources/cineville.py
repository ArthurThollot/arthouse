"""Cineville source.

Uses api.cineville.nl directly -- the "CultureKit" backend that Cineville's
own Next.js frontend calls (found via their shipped JS bundle: the API
client's `cultureKitApiUrl` config value, then reverse-engineering the
`/venues`, `/events`, `/productions` resource paths and their `field[op]`
filter syntax by triggering validation errors). No auth needed.

This is the best-covered source: every venue already carries lat/lon (no
geocoding needed) and every production carries `attributes.spokenLanguages`,
so the language filter here is exact, unlike Pathé's tag-based guess.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from geo import within_radius

API = "https://api.cineville.nl"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
AMS_TZ = ZoneInfo("Europe/Amsterdam")
PAGE_LIMIT = 100


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _paginate(session, path, params):
    params = dict(params)
    params["page[limit]"] = PAGE_LIMIT
    items = []
    next_href = None
    while True:
        if next_href:
            resp = session.get(f"{API}{next_href}", timeout=20)
        else:
            resp = session.get(f"{API}{path}", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        embedded = data.get("_embedded", {})
        # There's exactly one key under _embedded per resource type.
        items.extend(next(iter(embedded.values()), []))
        next_href = data.get("_links", {}).get("next", {}).get("href")
        if not next_href:
            break
    return items


def _venues_in_range(session, home_lat, home_lon, radius_km, excluded):
    venues = []
    for v in _paginate(session, "/venues", {}):
        if v["id"] in excluded:
            continue
        addr = v.get("address") or {}
        lat, lon = addr.get("latitude"), addr.get("longitude")
        if lat is None or lon is None:
            continue
        if within_radius(home_lat, home_lon, lat, lon, radius_km):
            venues.append({"id": v["id"], "name": v["name"], "lat": lat, "lon": lon})
    return venues


def _date_window_utc(days_ahead: int):
    now_local = datetime.now(AMS_TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=days_ahead)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    return start_local.astimezone(timezone.utc).strftime(fmt), end_local.astimezone(timezone.utc).strftime(fmt)


def fetch(config: dict) -> list[dict]:
    home = config["home"]
    excluded = set(config.get("excluded_cinemas", []))
    allowed_languages = set(config.get("allowed_languages", []))
    session = _session()

    venues = _venues_in_range(session, home["lat"], home["lon"], config["radius_km"], excluded)
    if not venues:
        return []
    venue_by_id = {v["id"]: v for v in venues}

    start_utc, end_utc = _date_window_utc(config["days_ahead"])
    event_params = {
        "venueId[in][]": list(venue_by_id.keys()),
        "startDate[gte]": start_utc,
        "startDate[lte]": end_utc,
    }
    events = _paginate(session, "/events", event_params)
    if not events:
        return []

    production_ids = sorted({e["productionId"] for e in events if e.get("productionId")})
    productions_by_id = {}
    # Batch in chunks to keep query strings reasonable.
    for i in range(0, len(production_ids), 50):
        chunk = production_ids[i : i + 50]
        prods = _paginate(session, "/productions", {"id[in][]": chunk})
        for p in prods:
            productions_by_id[p["id"]] = p

    records = []
    for event in events:
        production = productions_by_id.get(event["productionId"])
        if production is None:
            continue
        spoken = set(production.get("attributes", {}).get("spokenLanguages") or [])
        if not spoken & allowed_languages:
            continue

        venue = venue_by_id[event["venueId"]]
        start_local = datetime.fromisoformat(event["startDate"].replace("Z", "+00:00")).astimezone(AMS_TZ)

        attrs = production.get("attributes", {})
        release_year = attrs.get("releaseYear")
        poster_url = (production.get("assets", {}).get("poster") or {}).get("url") or (
            production.get("assets", {}).get("cover") or {}
        ).get("url")
        records.append(
            {
                "source": "cineville",
                "film_title": production.get("title", "?"),
                "film_year": str(release_year) if release_year else None,
                # premiereDate is when Cineville started showing it, not the
                # film's original release year -- what we want for a "new"
                # badge (a classic revival should still count as new
                # programming).
                "release_date": attrs.get("premiereDate"),
                "runtime_minutes": attrs.get("duration"),
                "poster_url": poster_url,
                "description": production.get("localizableAttributes", {}).get("description"),
                "cast": ", ".join((attrs.get("cast") or [])[:5]) or None,
                "director": ", ".join(attrs.get("directors") or []) or None,
                "cinema_name": venue["name"],
                "distance_km": None,  # filled in by build.py
                "start_time": start_local.strftime("%Y-%m-%d %H:%M:%S"),
                "language_tag": "/".join(sorted(spoken & allowed_languages)).upper(),
                "booking_url": event.get("ticketingUrl"),
                "_lat": venue["lat"],
                "_lon": venue["lon"],
            }
        )
    return records
