"""Amsterdam metro and city-rail stations, usable as a pickable "home" anchor.

Why stations and not addresses: nobody knows their own lat/lon, but everyone
knows which stop they live near. Picking "De Pijp" gets you within a few
hundred metres of home, which is well inside the noise of the bike-time
estimate anyway -- that's straight-line distance at an assumed speed, not a
routed journey (see geo.BIKE_BUCKETS).

Coordinates are approximate station-centre values. Grouped by part of town
because that's how you actually look for the one near you.

If your stop isn't here, or you want real precision, set home.lat/home.lon
in config.yaml directly -- that always wins over home.station.
"""

# group -> [(name, lat, lon), ...]
STATIONS: dict[str, list[tuple[str, float, float]]] = {
    "Centre": [
        ("Centraal Station", 52.3791, 4.9003),
        ("Nieuwmarkt", 52.3723, 4.9006),
        ("Rokin", 52.3690, 4.8925),
        ("Waterlooplein", 52.3676, 4.9027),
        ("Vijzelgracht", 52.3620, 4.8905),
        ("Weesperplein", 52.3617, 4.9077),
    ],
    "West": [
        ("Sloterdijk", 52.3886, 4.8369),
        ("Isolatorweg", 52.3946, 4.8339),
        ("Jan van Galenstraat", 52.3740, 4.8497),
        ("Postjesweg", 52.3653, 4.8434),
        ("Lelylaan", 52.3578, 4.8331),
        ("Henk Sneevlietweg", 52.3436, 4.8355),
    ],
    "South": [
        ("De Pijp", 52.3547, 4.8916),
        ("Europaplein", 52.3411, 4.8917),
        ("RAI", 52.3384, 4.8890),
        ("Zuid", 52.3390, 4.8730),
        ("Amstelveenseweg", 52.3417, 4.8562),
    ],
    "East": [
        ("Wibautstraat", 52.3547, 4.9107),
        ("Muiderpoort", 52.3606, 4.9276),
        ("Science Park", 52.3557, 4.9525),
        ("Amstel", 52.3468, 4.9180),
        ("Spaklerweg", 52.3383, 4.9143),
        ("Overamstel", 52.3325, 4.9075),
    ],
    "North": [
        ("Noord", 52.3990, 4.9180),
        ("Noorderpark", 52.3901, 4.9166),
    ],
    "Southeast": [
        ("Van der Madeweg", 52.3327, 4.9250),
        ("Duivendrecht", 52.3237, 4.9350),
        ("Diemen Zuid", 52.3308, 4.9527),
        ("Venserpolder", 52.3232, 4.9436),
        ("Strandvliet", 52.3145, 4.9440),
        ("Bijlmer ArenA", 52.3122, 4.9470),
        ("Bullewijk", 52.3050, 4.9524),
        ("Holendrecht", 52.2961, 4.9583),
        ("Reigersbos", 52.2905, 4.9727),
        ("Gein", 52.2872, 4.9800),
        ("Verrijn Stuartweg", 52.3172, 4.9700),
        ("Ganzenhoef", 52.3170, 4.9640),
        ("Kraaiennest", 52.3145, 4.9736),
        ("Gaasperplas", 52.3117, 4.9862),
    ],
}


def all_stations() -> list[tuple[str, float, float]]:
    return [s for group in STATIONS.values() for s in group]


def resolve(name: str) -> tuple[float, float]:
    """Station name (case-insensitive) -> (lat, lon). Raises on a typo rather
    than silently falling back, so a misspelled config is loud."""
    wanted = name.strip().lower()
    for station_name, lat, lon in all_stations():
        if station_name.lower() == wanted:
            return lat, lon
    known = ", ".join(sorted(s[0] for s in all_stations()))
    raise ValueError(f"Unknown station {name!r}. Known stations: {known}")
