# Arthouse

A personal script that pulls movie showtimes from the cinemas near you in
Amsterdam and writes one page you can scroll through -- one collapsible card
per cinema, closest first, with filters for text, day, cinema, and biking
distance, plus each film's IMDb rating. No account required for the
scraping itself, no hosting, run it whenever you want an up-to-date view.

## Page features

- **Two tabs**: **By Cinema** (one collapsible card per cinema, closest
  first) and **By Movie** (a big-poster browse grid, one tile per distinct
  film -- like a streaming app's browse screen). Both tabs share the same
  filters: switch tabs and whatever's currently filtered stays filtered.
- **Refresh button** in the header -- pulls fresh data without going back to
  the terminal (see "Running" below). Only works when served via `./run.sh`;
  the button is automatically disabled with an explanatory tooltip if you
  open the HTML file directly instead.
- **Text filter** -- matches film title or cinema name.
- **Day pills** -- one day visible at a time, defaults to today; fetches up
  to a week ahead (hard-capped in `build.py` regardless of config).
- **Minimum-rating slider** -- drag to a threshold (0 = no filter, hides
  unrated films once above 0).
- **"Around this time" slider** -- drag to a target time and only see
  showtimes within an hour of it either way; the label shows the matching
  Unicode clock-face emoji for a bit of fun.
- **Cinema checkboxes** (sortable by distance or A-Z; cinemas listed in
  `default_off_cinemas` start unchecked, grouped at the bottom) and
  **biking-time checkboxes** -- toggle whole cinemas or distance bands
  on/off (only bands that actually have a cinema in them are shown).
- **IMDb rating** -- a small bar + number next to each film, via the OMDb
  API (see below). Films OMDb doesn't recognize just show no rating.
- **New / Last chance badges** -- New = first showing within the last 14
  days (all three sources). Last chance is Pathé-only (their own explicit
  "last chance" tag) -- Cineville/Vue don't expose an equivalent signal.
- **Click a film's title** (By Cinema tab) to expand a poster, description,
  genre, runtime, director, and cast beneath it -- the By Movie tab shows
  all of that up front since browsing by film is the point of that tab.
  Pathé, Cineville and Vue are all Dutch sites, so their own descriptions
  are in Dutch -- when OMDb has a match for that film, its English
  plot/cast/director/genre are used instead; otherwise it falls back to
  the cinema's native (Dutch) text rather than showing nothing. Genre is
  also OMDb-only for Cineville and Vue, which don't expose it natively at
  all.

All filtering is client-side JS in the generated HTML.

## Sources

- **Pathé** -- their own internal JSON API (`pathe.nl/api/...`).
- **Cineville** -- their own internal JSON API (`api.cineville.nl`), which
  aggregates ~80 Dutch arthouse cinemas, including most of the Amsterdam
  ones (Kriterion, LAB111, Filmhallen, EYE, Studio/K, De Uitkijk, Melkweg,
  Het Ketelhuis, The Movies, Cinecenter, and more).
- **Vue** -- Amsterdam Houthavens only. Uses a real (headless) browser via
  Playwright, since Vue's API sits behind Cloudflare bot protection that
  blocks plain HTTP requests. Slowest and least stable of the three -- see
  "Known limitations" below.

None of these are documented public APIs -- they're the same endpoints each
site's own frontend calls, found by inspecting network traffic and shipped
JS bundles. They could change without notice.

**Ratings** come from [OMDb](https://www.omdbapi.com/), a free third-party
API that returns IMDb's rating by title/year. Deliberately not scraping
IMDb's own site: it's against their terms of service and defended by
aggressive anti-bot measures.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
cd ams-cinema-agenda
uv sync
uv run playwright install chromium   # only needed for the Vue source
```

Copy the template and edit it -- `config.yaml` is gitignored (it ends up
holding your home coordinates and OMDb API key), `config.example.yaml` is
the one checked into git:

```bash
cp config.example.yaml config.yaml
```

Fields:

- `home.lat` / `home.lon` -- defaults to Sloterdijk station. For more
  precision, look up your address at openstreetmap.org (right-click a spot
  -> "Show address" gives you the coordinates).
- `radius_km` -- how far out to look.
- `biking_speed_kmh` -- assumed average cycling speed, used only to turn
  distance into the "biking time" shown/filtered on the page. Straight-line
  distance / speed, not a routed cycling time -- a guide, not a promise.
- `days_ahead` -- how many days of showtimes to fetch (the page itself
  defaults to showing just today; this controls how much is available when
  you click further-out day pills). Capped at 7 in `build.py` regardless of
  this value.
- `allowed_languages` -- ISO 639-1 codes. A screening is kept only if the
  film's spoken language overlaps this list. Defaults to `[en, fr, es]`,
  which also excludes Dutch-language and Dutch-dubbed screenings (`nl` is
  never in the list).
- `sources` -- turn any of the three off, e.g. if Vue starts failing and
  you'd rather not deal with it.
- `default_off_cinemas` -- cinema names (case-insensitive) that are still
  fetched and listed in the Cinemas filter, but start unchecked and sorted
  to the bottom -- for places you rarely go but don't want to fully exclude.
  Use `excluded_cinemas` instead if you never want a cinema fetched at all.
- `omdb_api_key` -- free key from
  [omdbapi.com/apikey.aspx](https://www.omdbapi.com/apikey.aspx) (instant
  signup, no cost, 1000 lookups/day). Leave blank to skip ratings entirely.
  New keys sometimes need email confirmation before they're active -- if
  the terminal prints `[ratings] OMDb error: Invalid API key!`, check your
  inbox for an activation link before assuming something's broken.

## Running

```bash
./run.sh
```

Builds once, then serves the page at `http://localhost:8765/` with a
**Refresh** button in the header that pulls fresh data on demand -- nothing
runs on a timer, data only changes when you load the page or click
Refresh. Press Ctrl+C in the terminal to stop it.

For a one-shot build without the server (e.g. to just check
`output/index.html` in a text editor), `uv run python build.py` still works
directly -- but opening that file's `file://` URL in a browser means the
Refresh button can't reach `/refresh` (no server behind it); use `./run.sh`
if you want Refresh to actually work.

## Known limitations

- **Language filtering is exact for Cineville, best-effort for Pathé and
  Vue.** Cineville exposes each film's actual spoken language(s), so its
  filter is precise. Pathé and Vue don't expose that field at all -- for
  those two, only explicitly Dutch-dubbed screenings are dropped (Pathé's
  `nlnl` version tag, Vue's "Nederlandse Versie" session attribute), plus a
  small manual list of Pathé tags for languages known not to be in
  `allowed_languages` (Bollywood, Polish, Turkish films). A film in these
  two sources that's original-language German, Japanese, Korean, etc. and
  screened with subtitles (not dubbed) will *not* be filtered out --
  there's no data available to catch that case. Revisit if it turns out to
  be common in practice.
- **Vue is fragile by design.** It's the only source requiring a headless
  browser (Cloudflare blocks plain requests to its API), so it's slower
  (~5-10s) and the piece most likely to break if Vue changes their site. If
  it starts failing, set `sources.vue: false` in config.yaml rather than
  debugging it -- it's a single cinema, not worth the upkeep.
- **Undocumented APIs.** Pathé's and Cineville's endpoints aren't public or
  documented; they're what their own frontends call today. No auth or
  rate-limit issues expected for occasional manual runs, but they could
  change shape or disappear without notice.
- If any one source fails outright (network error, API shape change),
  `build.py` logs it and continues with the other two rather than failing
  the whole run.
- **Ratings can miss real matches.** OMDb is looked up by title + the
  film's release year as each source reports it. Cineville's `releaseYear`
  is the film's true original year (accurate even for revival
  screenings), but Pathé/Vue only expose a Dutch release/screening date --
  for a rare classics re-release there, the year passed to OMDb could be
  the re-release year rather than the original, and OMDb's year match is
  exact, so that film just shows no rating rather than a wrong one.
  Ratings are cached in `ratings_cache.json` (gitignored) so repeat runs
  don't re-query OMDb for films you've already seen.

## Possible follow-ups (not built)

- A small live web app with a radius slider, instead of a static page you
  regenerate by hand.
- Better language detection for Pathé/Vue (e.g. cross-referencing a movie
  database for original language) to close the gap noted above.
