#!/usr/bin/env python3
"""Fetch showtimes from all enabled sources and render output/index.html.

Usage: python build.py [--config config.yaml]
"""

import argparse
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

import ratings
from geo import BIKE_BUCKETS, bike_bucket, bike_minutes, haversine_km
from sources import cineville, pathe, vue

ROOT = Path(__file__).parent
SOURCE_MODULES = {"pathe": pathe, "cineville": cineville, "vue": vue}
MAX_DAYS_AHEAD = 7  # hard cap: never show more than a week out, regardless of config
DESCRIPTION_MAX_CHARS = 220
DESCRIPTION_FULL_MAX_CHARS = 600  # for the movie-gallery tab; a defensive cap, not a real limit
NEW_RELEASE_WINDOW_DAYS = 14


def _is_new_release(release_date: str | None, today) -> bool:
    if not release_date:
        return False
    try:
        released = datetime.strptime(release_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return 0 <= (today - released).days <= NEW_RELEASE_WINDOW_DAYS


def _truncate(text: str | None, max_chars: int) -> str | None:
    if not text:
        return None
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def fetch_all(config: dict) -> list[dict]:
    records = []
    for name, module in SOURCE_MODULES.items():
        if not config.get("sources", {}).get(name, True):
            print(f"[{name}] skipped (disabled in config)")
            continue
        try:
            source_records = module.fetch(config)
        except Exception:
            print(f"[{name}] FAILED, skipping this source:", file=sys.stderr)
            traceback.print_exc()
            continue
        print(f"[{name}] {len(source_records)} showtimes")
        records.extend(source_records)
    return records


def finalize(records: list[dict], home: dict, now: datetime) -> list[dict]:
    """Fill in distance, parse start_time, drop past showtimes, sort."""
    finalized = []
    for r in records:
        start = datetime.strptime(r["start_time"], "%Y-%m-%d %H:%M:%S")
        if start < now:
            continue
        distance_km = haversine_km(home["lat"], home["lon"], r["_lat"], r["_lon"])
        finalized.append(
            {
                "source": r["source"],
                "film_title": r["film_title"],
                "film_year": r.get("film_year"),
                "poster_url": r.get("poster_url"),
                "description": _truncate(r.get("description"), DESCRIPTION_MAX_CHARS),
                "description_full": _truncate(r.get("description"), DESCRIPTION_FULL_MAX_CHARS),
                "cast": r.get("cast"),
                "director": r.get("director"),
                "genre": r.get("genre"),
                "runtime_minutes": r.get("runtime_minutes"),
                "is_new": _is_new_release(r.get("release_date"), now.date()),
                "is_last_chance": bool(r.get("is_last_chance")),
                "cinema_name": r["cinema_name"],
                "cinema_lat": r["_lat"],
                "cinema_lon": r["_lon"],
                "distance_km": round(distance_km, 1),
                "start_dt": start,
                "day_label": start.strftime("%A %-d %B"),
                "time_label": start.strftime("%H:%M"),
                "minutes_of_day": start.hour * 60 + start.minute,
                "language_tag": r["language_tag"],
                "booking_url": r.get("booking_url"),
                "imdb_rating": None,  # filled in by attach_ratings()
            }
        )
    finalized.sort(key=lambda r: (r["start_dt"], r["distance_km"], r["film_title"]))
    return finalized


def attach_ratings(records: list[dict], config: dict) -> None:
    """Mutates records in place: fills in 'imdb_rating', and where OMDb has
    a match, overrides description/cast/director/genre with OMDb's English
    versions (each source's own text is Dutch -- Pathé, Cineville and Vue
    are all Dutch sites; Cineville and Vue don't expose genre at all).
    Falls back to each source's native values when OMDb has no match for
    that film."""
    api_key = (config.get("omdb_api_key") or "").strip()
    if not api_key:
        print("[ratings] skipped (no omdb_api_key set in config.yaml)")
        return
    title_years = {(r["film_title"], r["film_year"]) for r in records}
    omdb_map = ratings.get_ratings(title_years, api_key)
    for r in records:
        data = omdb_map.get((r["film_title"], r["film_year"]))
        if data is None:
            continue
        # .get() rather than [...]: cached entries from an older run may
        # predate a field added here since, and shouldn't crash the build.
        r["imdb_rating"] = data.get("rating")
        if data.get("plot"):
            r["description"] = _truncate(data["plot"], DESCRIPTION_MAX_CHARS)
            r["description_full"] = _truncate(data["plot"], DESCRIPTION_FULL_MAX_CHARS)
        if data.get("cast"):
            r["cast"] = data["cast"]
        if data.get("director"):
            r["director"] = data["director"]
        if data.get("genre"):
            r["genre"] = data["genre"]
    print(f"[ratings] {len(omdb_map)}/{len(title_years)} films matched on OMDb")


def render(records: list[dict], config: dict, generated_at: datetime) -> str:
    speed_kmh = config.get("biking_speed_kmh", 15)
    today = generated_at.date()

    by_cinema = defaultdict(list)
    for r in records:
        by_cinema[r["cinema_name"]].append(r)

    cinemas = []
    for name, items in by_cinema.items():
        items.sort(key=lambda r: r["start_dt"])
        by_day = defaultdict(list)
        for item in items:
            by_day[item["start_dt"].date()].append(item)
        days = [
            {"date": day.isoformat(), "label": day_items[0]["day_label"], "showtimes": day_items}
            for day, day_items in sorted(by_day.items())
        ]
        distance_km = items[0]["distance_km"]
        minutes = bike_minutes(distance_km, speed_kmh)
        bucket_slug, bucket_label = bike_bucket(minutes)
        count_today = len(by_day.get(today, []))
        cinemas.append(
            {
                "name": name,
                "lat": items[0]["cinema_lat"],
                "lon": items[0]["cinema_lon"],
                "distance_km": distance_km,
                "bike_minutes": round(minutes),
                "bucket_slug": bucket_slug,
                "bucket_label": bucket_label,
                "count_today": count_today,
                "days": days,
            }
        )
    cinemas.sort(key=lambda c: c["distance_km"])

    # One entry per distinct film (by title+year) for the "By Movie" tab --
    # first occurrence wins; attach_ratings() already made every occurrence
    # of a given film identical on the fields that matter here (rating,
    # description, cast, director, genre), so which one we keep doesn't
    # matter. Best-rated first so the tab leads with what's worth watching.
    seen_films = {}
    for r in records:
        key = (r["film_title"], r["film_year"])
        if key not in seen_films:
            seen_films[key] = r
    distinct_films = sorted(
        seen_films.values(), key=lambda r: (-(r["imdb_rating"] or 0), r["film_title"])
    )

    default_off = {n.lower() for n in config.get("default_off_cinemas", [])}
    cinema_checkbox_order = [{"name": c["name"], "default_off": False} for c in cinemas if c["name"].lower() not in default_off] + [
        {"name": c["name"], "default_off": True} for c in cinemas if c["name"].lower() in default_off
    ]

    bucket_order = [(slug, label) for _, slug, label in BIKE_BUCKETS]
    used_buckets = {c["bucket_slug"] for c in cinemas}
    buckets_present = [(slug, label) for slug, label in bucket_order if slug in used_buckets]

    day_pills = []
    for i in range(config["days_ahead"]):
        d = today + timedelta(days=i)
        if i == 0:
            label = "Today"
        elif i == 1:
            label = "Tomorrow"
        else:
            label = d.strftime("%a %-d %b")
        day_pills.append({"date": d.isoformat(), "label": label})

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    template = env.get_template("agenda.html.j2")
    return template.render(
        cinemas=cinemas,
        home=config["home"],
        distinct_films=distinct_films,
        cinema_checkbox_order=cinema_checkbox_order,
        buckets=buckets_present,
        day_pills=day_pills,
        today_iso=today.isoformat(),
        radius_km=config["radius_km"],
        generated_at=generated_at.strftime("%A %-d %B %Y, %H:%M"),
        total_count=len(records),
    )


def run_build(config_path: Path) -> Path:
    """Full pipeline: fetch -> finalize -> ratings -> render -> write. Used by
    both the CLI entry point and serve.py's /refresh handler."""
    config = load_config(config_path)
    config["days_ahead"] = min(config.get("days_ahead", MAX_DAYS_AHEAD), MAX_DAYS_AHEAD)
    now = datetime.now()
    raw_records = fetch_all(config)
    records = finalize(raw_records, config["home"], now)
    attach_ratings(records, config)

    html = render(records, config, now)
    output_path = ROOT / "output" / "index.html"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(html)

    print(f"\nWrote {len(records)} showtimes to {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = parser.parse_args()
    run_build(Path(args.config))


if __name__ == "__main__":
    main()
