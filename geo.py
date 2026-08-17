"""Distance helpers for filtering cinemas by radius from home."""

import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in kilometers."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def within_radius(home_lat: float, home_lon: float, lat: float, lon: float, radius_km: float) -> bool:
    return haversine_km(home_lat, home_lon, lat, lon) <= radius_km


# Upper bound (minutes, exclusive) -> (slug, label). Straight-line distance
# converted at a configurable speed, not routed cycling time, so treat as a
# rough guide -- actual bike routes are rarely as the crow flies.
BIKE_BUCKETS = [
    (5, "0-5", "0-5 min"),
    (10, "5-10", "5-10 min"),
    (15, "10-15", "10-15 min"),
    (18, "15-18", "15-18 min"),
    (20, "18-20", "18-20 min"),
    (30, "20-30", "20-30 min"),
    (float("inf"), "30plus", "30+ min"),
]


def bike_minutes(distance_km: float, speed_kmh: float) -> float:
    return distance_km / speed_kmh * 60


def bike_bucket(minutes: float) -> tuple[str, str]:
    for upper, slug, label in BIKE_BUCKETS:
        if minutes < upper:
            return slug, label
    return BIKE_BUCKETS[-1][1], BIKE_BUCKETS[-1][2]
