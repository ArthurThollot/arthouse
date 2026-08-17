"""Pathé source.

Uses pathe.nl's internal JSON API (the same one their own frontend calls --
found by inspecting the Angular `ng-state` transfer-state blob embedded in
their server-rendered HTML). No auth needed, but plain requests get a 403
without realistic browser headers.

Known gap: Pathé exposes no per-film "original language" field, so the
EN/FR/ES filter here is best-effort: it drops Dutch-dubbed screenings
outright (the only two version values Pathé has are "ov" and "nlnl"), and
additionally drops films tagged with a small set of known non-EN/FR/ES
language tags ("bollywood", "poolsefilm", "turksefilm"). A film in "ov"
that's actually e.g. Japanese or German audio would slip through uncaught --
revisit if that turns out to be common in practice.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

from geo import within_radius

MAX_WORKERS = 12

BASE = "https://www.pathe.nl/api"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "nl-NL,nl;q=0.9",
}

DUTCH_DUB_VERSION = "nlnl"
NON_ALLOWED_LANGUAGE_TAGS = {"bollywood", "poolsefilm", "turksefilm"}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _cinemas_in_range(session, home_lat, home_lon, radius_km, excluded):
    resp = session.get(f"{BASE}/cinemas", timeout=20)
    resp.raise_for_status()
    cinemas = []
    for entry in resp.json():
        if entry["slug"] in excluded:
            continue
        for theater in entry.get("theaters", []):
            gps = theater.get("gpsPosition") or {}
            lat, lon = gps.get("x"), gps.get("y")
            if lat is None or lon is None:
                continue
            if within_radius(home_lat, home_lon, lat, lon, radius_km):
                cinemas.append(
                    {
                        "slug": entry["slug"],
                        "name": theater.get("name") or entry.get("name"),
                        "lat": lat,
                        "lon": lon,
                    }
                )
    return cinemas


def fetch(config: dict) -> list[dict]:
    home = config["home"]
    excluded = set(config.get("excluded_cinemas", []))
    session = _session()

    cinemas = _cinemas_in_range(session, home["lat"], home["lon"], config["radius_km"], excluded)
    if not cinemas:
        return []
    cinema_by_slug = {c["slug"]: c for c in cinemas}

    today = date.today()
    date_window = [(today + timedelta(days=i)).isoformat() for i in range(config["days_ahead"])]
    date_window_set = set(date_window)

    resp = session.get(f"{BASE}/shows", timeout=20)
    resp.raise_for_status()
    films = resp.json().get("shows", [])

    def _relevant_cinemas(film):
        slug = film["slug"]
        try:
            resp = session.get(f"{BASE}/show/{slug}/cinemas", timeout=20)
            resp.raise_for_status()
            per_cinema = resp.json()
        except requests.RequestException:
            return film, {}
        relevant = {
            cslug: days
            for cslug, days in per_cinema.items()
            if cslug in cinema_by_slug and date_window_set & set(days.get("days", {}))
        }
        return film, relevant

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        film_availability = list(pool.map(_relevant_cinemas, films))

    candidates = [(film, relevant) for film, relevant in film_availability if relevant]

    def _film_allowed(film_and_relevant):
        film, relevant = film_and_relevant
        try:
            resp = session.get(f"{BASE}/show/{film['slug']}", timeout=20)
            resp.raise_for_status()
            detail = resp.json()
        except requests.RequestException:
            return film, relevant, False, {}
        allowed = not (NON_ALLOWED_LANGUAGE_TAGS & set(detail.get("tags") or []))
        return film, relevant, allowed, detail

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        checked = list(pool.map(_film_allowed, candidates))

    showtime_jobs = []
    for film, relevant, allowed, detail in checked:
        if not allowed:
            continue
        for cinema_slug, day_info in relevant.items():
            for day in date_window_set & set(day_info.get("days", {})):
                showtime_jobs.append((film, cinema_by_slug[cinema_slug], day, detail))

    def _fetch_showtimes(job):
        film, cinema, day, detail = job
        try:
            resp = session.get(
                f"{BASE}/show/{film['slug']}/showtimes/{cinema['slug']}/{day}", timeout=20
            )
            resp.raise_for_status()
            return film, cinema, resp.json(), detail
        except requests.RequestException:
            return film, cinema, [], detail

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(_fetch_showtimes, showtime_jobs))

    records = []
    for film, cinema, showtimes, detail in results:
        poster_url = (detail.get("posterPath") or {}).get("md") or (detail.get("posterPath") or {}).get("lg")
        description = detail.get("synopsis")
        cast = ", ".join((detail.get("actors") or [])[:5]) or None
        director = ", ".join(detail.get("directors") or []) or None
        genre = ", ".join((detail.get("genres") or [])[:2]) or None  # Dutch (e.g. "Actie"); OMDb's English genre wins when matched
        release_date = (film.get("releaseAt") or {}).get("NL_NL") or None
        runtime_minutes = detail.get("duration")
        is_last_chance = "lastchance" in (detail.get("tags") or [])
        for st in showtimes:
            if st.get("version") == DUTCH_DUB_VERSION:
                continue
            records.append(
                {
                    "source": "pathe",
                    "film_title": film["title"],
                    "film_year": (release_date or "")[:4] or None,
                    "release_date": release_date,
                    "runtime_minutes": runtime_minutes,
                    "is_last_chance": is_last_chance,
                    "poster_url": poster_url,
                    "description": description,
                    "cast": cast,
                    "director": director,
                    "genre": genre,
                    "cinema_name": cinema["name"],
                    "distance_km": None,  # filled in by build.py
                    "start_time": st["time"],  # "YYYY-MM-DD HH:MM:SS"
                    "language_tag": "OV" if st.get("version") == "ov" else st.get("version", "?"),
                    "booking_url": st.get("refCmd"),
                    "_lat": cinema["lat"],
                    "_lon": cinema["lon"],
                }
            )
    return records
