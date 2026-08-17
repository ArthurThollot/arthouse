"""Vue source (Amsterdam Houthavens -- the only Vue location in range).

Vue's showtimes come from `/api/microservice/showings/cinemas/{id}/films`,
found by recording network traffic in a real browser session. That endpoint
is undocumented but otherwise a plain JSON API -- except it sits behind
Cloudflare bot management: plain `requests` calls get 401'd (confirmed even
with a warmed-up cookie jar reused across calls), while the exact same
fetch issued from inside an actual Playwright browser page succeeds
consistently. So this module launches a real (headless) browser, loads the
Vue Amsterdam page once to pass Cloudflare's check, then calls the API via
`page.evaluate` (i.e. as a same-origin fetch from inside that browser) for
each date.

This is the shakiest of the three sources by a wide margin: undocumented
endpoint, fronted by active bot detection, one extra runtime dependency
(a downloaded Chromium binary) and several seconds of browser startup per
run. There's only one cinema in range, so if this breaks, the fix is to
just drop it (set `sources.vue: false` in config.yaml) rather than debug it.

Known gap: same as Pathé -- no per-film "original language" field, so only
sessions explicitly tagged "Nederlandse Versie" (Dutch dub) are dropped;
everything else is assumed OV. A non-EN/FR/ES film shown OV would slip
through uncaught.
"""

from datetime import date, timedelta

from playwright.sync_api import sync_playwright

from geo import within_radius

WHATS_ON_URL = "https://www.vuecinemas.nl/cinema/amsterdam/nu-in-de-bioscoop"

# The only Vue cinema in the Amsterdam area (Houthavens). Vue's own API
# doesn't expose venue coordinates, so this is hardcoded rather than
# discovered (geocoded once via OpenStreetMap Nominatim) -- update if Vue
# opens/closes an Amsterdam-area location.
AMSTERDAM_CINEMA = {"id": "1026", "name": "Vue Amsterdam", "lat": 52.3977011, "lon": 4.8764905}

DUTCH_DUB_LANGUAGE_NAMES = {"nederlandse versie"}

_FETCH_JS = """async (params) => {
    const url = `/api/microservice/showings/cinemas/${params.cinemaId}/films`
        + `?showingDate=${params.showingDate}&minEmbargoLevel=3`
        + `&includesSession=true&includeSessionAttributes=true`;
    const r = await fetch(url);
    if (!r.ok) return null;
    return await r.json();
}"""


def _records_from_payload(payload) -> list[dict]:
    records = []
    for film in (payload or {}).get("result", []):
        title = film.get("filmTitle", "?")
        release_date = (film.get("releaseDate") or "")[:10] or None  # "YYYY-MM-DD"
        film_year = (release_date or "")[:4] or None
        runtime_minutes = film.get("runningTime") if not film.get("isDurationUnknown") else None
        poster_url = film.get("posterImageSrc")
        description = film.get("synopsisShort")
        cast_raw = film.get("cast") or ""
        cast = ", ".join(name.strip() for name in cast_raw.split(",")[:5] if name.strip()) or None
        director = film.get("director") or None
        for group in film.get("showingGroups", []):
            for session_info in group.get("sessions", []):
                lang_names = {
                    a["name"].strip().lower()
                    for a in session_info.get("attributes", [])
                    if a.get("attributeType") == "Language"
                }
                if lang_names & DUTCH_DUB_LANGUAGE_NAMES:
                    continue
                start = session_info.get("startTime")  # "YYYY-MM-DDTHH:MM:SS", local time
                if not start:
                    continue
                booking_path = session_info.get("bookingUrl")
                records.append(
                    {
                        "source": "vue",
                        "film_title": title,
                        "film_year": film_year,
                        "release_date": release_date,
                        "runtime_minutes": runtime_minutes,
                        "poster_url": poster_url,
                        "description": description,
                        "cast": cast,
                        "director": director,
                        "cinema_name": AMSTERDAM_CINEMA["name"],
                        "distance_km": None,  # filled in by build.py
                        "start_time": start.replace("T", " "),
                        "language_tag": "OV",
                        "booking_url": f"https://www.vuecinemas.nl{booking_path}" if booking_path else None,
                        "_lat": AMSTERDAM_CINEMA["lat"],
                        "_lon": AMSTERDAM_CINEMA["lon"],
                    }
                )
    return records


def fetch(config: dict) -> list[dict]:
    home = config["home"]
    if AMSTERDAM_CINEMA["id"] in set(config.get("excluded_cinemas", [])):
        return []
    if not within_radius(home["lat"], home["lon"], AMSTERDAM_CINEMA["lat"], AMSTERDAM_CINEMA["lon"], config["radius_km"]):
        return []

    today = date.today()
    days = [(today + timedelta(days=i)).isoformat() + "T00:00:00" for i in range(config["days_ahead"])]

    records = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(WHATS_ON_URL, wait_until="networkidle", timeout=45000)
                for showing_date in days:
                    payload = page.evaluate(
                        _FETCH_JS, {"cinemaId": AMSTERDAM_CINEMA["id"], "showingDate": showing_date}
                    )
                    records.extend(_records_from_payload(payload))
            finally:
                browser.close()
    except Exception:
        # Vue is best-effort: any failure here (Cloudflare change, layout
        # change, browser crash) should drop this source, not the whole run.
        return []
    return records
