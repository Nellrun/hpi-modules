# hpi-modules

Additional modules for [karlicoss/HPI](https://github.com/karlicoss/HPI) — the
Human Programming Interface, a Python package (`my`) that turns your scattered
"digital life" into ordinary Python objects.

Currently shipping:

| Module                         | Description                                                              |
| ------------------------------ | ------------------------------------------------------------------------ |
| [`my.letterboxd`](#letterboxd) | Diary entries, ratings, reviews, watchlist and likes from Letterboxd     |
| [`my.trakt`](#trakt)           | History, ratings, watchlist, likes, followers/following from Trakt.tv    |

The repository is organised as a **namespace package** (PEP 420), so it
co-exists peacefully with the upstream `karlicoss/HPI` and any other HPI
overlay (such as [purarue/HPI](https://github.com/purarue/HPI)).

More integrations are planned — the project layout, tooling
(`pyproject.toml`, ruff/mypy configs, CI, tests) is already set up for that.

---

## Table of contents

- [Why](#why)
- [Installation](#installation)
- [Letterboxd](#letterboxd)
  - [Step 1. Download your Letterboxd export](#step-1-download-your-letterboxd-export)
  - [Step 2. Put the export somewhere convenient](#step-2-put-the-export-somewhere-convenient)
  - [Step 3. Configure `my.config`](#step-3-configure-myconfig)
  - [Step 4. Verify the setup](#step-4-verify-the-setup)
  - [Public API](#public-api)
  - [Domain model](#domain-model)
  - [Usage examples](#usage-examples)
- [Trakt](#trakt)
  - [Step 1. Produce a snapshot](#step-1-produce-a-snapshot)
  - [Step 2. Configure `my.config`](#step-2-configure-myconfig-trakt)
  - [Step 3. Verify the setup](#step-3-verify-the-setup-trakt)
  - [Public API (`my.trakt`)](#public-api-mytrakt)
  - [Domain model (`my.trakt.common`)](#domain-model-mytraktcommon)
  - [Usage examples (`my.trakt`)](#usage-examples-mytrakt)
- [CLI: `hpi query`](#cli-hpi-query)
- [Caching (cachew)](#caching-cachew)
- [Logging](#logging)
- [Development](#development)
- [Adding new modules to this repository](#adding-new-modules-to-this-repository)
- [License](#license)

---

## Why

HPI removes the boundary between "data in the cloud" and "regular code that
runs locally". You configure the path to the export once, and any of your
scripts can do:

```python
from my.letterboxd.all import diary
for entry in diary():
    ...
```

…getting back not raw CSV but proper dataclasses, ready to be combined with
`pandas`, `matplotlib`, Jupyter and friends.

This library:

- **stores no data**. It only operates on what already lives on your disk
  (e.g. the archive you downloaded from Letterboxd);
- **is fully offline**. Not a single HTTP request is made;
- **needs no server or database** — it's just a Python package.

---

## Installation

### Option 1. `pipx` (recommended)

[`pipx`](https://pipx.pypa.io) installs the package into its own isolated
virtualenv and exposes the CLI on your `PATH` — no clashes with system
Python, no `--user` foot-guns.

```bash
git clone https://github.com/<your-fork>/hpi-modules.git
cd hpi-modules

pipx install --editable ".[cache]" --include-deps
```

Two important flags:

- `--editable` (or `-e`) — installs in editable mode, so any change you make
  under `src/my/letterboxd/*.py` is picked up immediately;
- `--include-deps` — exposes the `hpi` CLI that's shipped by the `HPI`
  dependency. Without it `pipx` only installs entry points declared by
  *this* package (we have none), so `hpi …` would not appear on your `PATH`.

The `[cache]` extra is optional but recommended — it pulls in
[`cachew`](https://github.com/karlicoss/cachew) for transparent caching.

If later you want to add the test/dev tooling to the same isolated env,
either reinstall with more extras or use `pipx inject`:

```bash
pipx install --force --editable ".[cache,tests,dev]" --include-deps
# or, additively:
pipx inject hpi-modules pytest mypy ruff cachew
```

> **Using [`uv`](https://docs.astral.sh/uv/)?** Install `HPI` as the tool
> (so the `hpi` binary lands on your `PATH`) and inject our package into
> the same isolated env in editable mode:
> ```bash
> uv tool install HPI --with-editable ".[cache]"
> ```

### Option 2. Plain `pip` in a virtualenv

If you'd rather not use `pipx`:

```bash
python3 -m venv ~/.venvs/hpi
source ~/.venvs/hpi/bin/activate

git clone https://github.com/<your-fork>/hpi-modules.git
cd hpi-modules
pip install -e ".[cache]"
```

This pulls in all dependencies (including `HPI`) and installs the package in
editable mode.

For local development add the `tests` and `dev` extras as well:

```bash
pip install -e ".[cache,tests,dev]"
```

- `cache` — pulls in [`cachew`](https://github.com/karlicoss/cachew) for
  transparent caching of parsing results;
- `tests` — `pytest` + `pytest-cov` to run the test suite;
- `dev` — `ruff` + `mypy` for linting and type-checking.

### Sanity check

```bash
hpi modules | grep letterboxd
hpi doctor my.letterboxd.export
```

`hpi doctor` will complain about a missing config — that's expected, we'll fix
it next.

---

## Letterboxd

### Step 1. Download your Letterboxd export

1. Open [Letterboxd Settings → Data](https://letterboxd.com/settings/data/).
2. Click **Export your data**. After a minute or two you'll get an email with a
   link to a ZIP named like `letterboxd-<username>-YYYY-MM-DD-HH-MM-utc.zip`.
3. Download the archive. You **don't have to unzip it** — the module reads
   data straight from the ZIP.

The archive contains CSV files:

```
letterboxd-username-2024-12-01-utc/
├── profile.csv
├── diary.csv          # diary of watches
├── ratings.csv        # your ratings
├── reviews.csv        # written reviews
├── watched.csv        # everything you've watched
├── watchlist.csv      # things you want to watch
├── comments.csv
├── likes/
│   ├── films.csv
│   ├── lists.csv
│   └── reviews.csv
└── lists/             # your custom lists
    └── …
```

Today the module parses `diary.csv`, `ratings.csv`, `reviews.csv`,
`watched.csv`, `watchlist.csv` and `likes/films.csv`. Adding more is
straightforward — the boilerplate is already in place.

### Step 2. Put the export somewhere convenient

Any of these works:

```bash
# just keep the archive:
mkdir -p ~/data/letterboxd
mv ~/Downloads/letterboxd-*.zip ~/data/letterboxd/

# or unpack it next to the archive:
unzip ~/Downloads/letterboxd-2024-12-01.zip -d ~/data/letterboxd/2024-12-01/
```

If you keep multiple successive exports around, the module will automatically
pick the **latest one** (sorted by name/mtime).

### Step 3. Configure `my.config`

HPI looks for your private config at `~/.config/my/my/config/__init__.py`
(on macOS: `~/Library/Application Support/my/my/config/__init__.py`; the path
can be overridden with the `MY_CONFIG` environment variable).

If you don't have a config yet, the fastest way to bootstrap one is:

```bash
hpi config create
```

Then add the `letterboxd` section:

```python
# ~/.config/my/my/config/__init__.py

class letterboxd:
    # Anything understood by my.core.get_files works:
    #
    #   * a str/Path to a ZIP file or to an unpacked directory
    #   * a glob:  '/data/letterboxd/letterboxd-*.zip'
    #   * a tuple/list of paths/globs
    #
    # If multiple exports are matched, the latest one (by sort order) is used.
    export_path = '~/data/letterboxd/letterboxd-*.zip'
```

Any of the following layouts is fine:

```python
class letterboxd:
    export_path = '~/data/letterboxd/2024-12-01/'   # a single directory

class letterboxd:
    export_path = (                                  # multiple sources
        '~/data/letterboxd/2024-06-01.zip',
        '~/data/letterboxd/2024-12-01/',
    )
```

### Step 4. Verify the setup

```bash
hpi doctor my.letterboxd.export
hpi doctor my.letterboxd.all
```

You should see `OK` and some metrics:

```
✅  OK  : my.letterboxd.export
        - inputs: 1
        - diary  : 314
        - reviews: 28
        - ratings: 287
        - watched: 314
        - watchlist: 92
        - likes  : 47
```

If something is off, add `--verbose` or enable debug logging:

```bash
LOGGING_LEVEL_my_letterboxd=debug hpi doctor my.letterboxd.export
```

### Public API

```python
# Low-level source (the official export only):
from my.letterboxd import export

export.diary()      # Iterator[Res[Diary]]
export.reviews()    # Iterator[Res[Review]]
export.ratings()    # Iterator[Res[Rating]]
export.watched()    # Iterator[Res[Watch]]
export.watchlist()  # Iterator[Res[WatchlistItem]]
export.likes()      # Iterator[Res[Like]]
export.films()      # Iterator[Film]    — every unique film
export.inputs()     # Sequence[Path]    — discovered sources

# The combined "facade" — preferred entry point for end-user scripts:
from my.letterboxd.all import diary, reviews, ratings, watched, watchlist, likes
```

`Res[T]` is `T | Exception`. Following the HPI convention, the parser does
not crash on a single bad row: it yields the exception as a regular value in
the stream, and you decide whether to skip or log it. Typical pattern:

```python
for item in diary():
    if isinstance(item, Exception):
        # malformed CSV row — log and move on
        continue
    ...
```

### Domain model

All types are frozen dataclasses built from primitive fields. This plays
nicely with `cachew`, `pandas` and any serializer.

```python
@dataclass(frozen=True, slots=True)
class Film:
    name: str
    year: int | None
    uri: str           # 'https://boxd.it/2a3b'
    @property
    def slug(self) -> str: ...   # 'parasite-2019'

@dataclass(frozen=True, slots=True)
class Diary:
    film: Film
    logged_date: date          # date the entry was logged in the diary
    watched_date: date | None  # actual watch date (if provided)
    rating: float | None       # 0.5 .. 5.0
    rewatch: bool
    tags: tuple[str, ...]
    review: str | None         # merged in from reviews.csv

class Review(Diary): ...       # an entry guaranteed to have a non-empty review

@dataclass(frozen=True, slots=True)
class Rating:        film: Film; rating: float;   date: date
@dataclass(frozen=True, slots=True)
class Watch:         film: Film; date: date
@dataclass(frozen=True, slots=True)
class WatchlistItem: film: Film; date: date
@dataclass(frozen=True, slots=True)
class Like:          film: Film; date: date
```

### Usage examples

#### Top 10 films by all-time rating

```python
from my.letterboxd.all import ratings

best = sorted(
    (r for r in ratings() if not isinstance(r, Exception)),
    key=lambda r: (r.rating, r.date),
    reverse=True,
)
for r in best[:10]:
    print(f"{r.rating:>3.1f}  {r.film.name} ({r.film.year})")
```

#### Films watched per month

```python
import pandas as pd
from my.letterboxd.all import diary

df = pd.DataFrame(
    {'logged': e.logged_date, 'rating': e.rating}
    for e in diary() if not isinstance(e, Exception)
).set_index('logged')

print(df.resample('ME').count())
```

#### Dump every review as Markdown

```python
from my.letterboxd.all import reviews

for r in reviews():
    if isinstance(r, Exception):
        continue
    rating = f" — **{r.rating}/5**" if r.rating else ""
    print(f"## {r.film.name} ({r.film.year}){rating}\n\n{r.review}\n")
```

#### "Which watchlist films has my friend already rated?"

(The kind of cross-source script HPI exists for.)

```python
from my.letterboxd.all import watchlist
# ... mix in data from any other my.* module here
```

---

## Trakt

Exposes everything [`traktexport`](https://github.com/purarue/traktexport)
dumps from your Trakt.tv account — full watch **history**, **ratings**,
**watchlist**, liked lists and comments, **followers** / **following**, plus
the raw aggregate **stats** Trakt keeps about you.

Unlike the Letterboxd CSV archive, a Trakt export is the full account state in
a single JSON file. It's also token-based (OAuth2 with a rotating refresh
token), so dumps are usually produced by a scheduled job rather than a manual
download. The recommended driver for that is
[`hpi-harvester`](https://github.com/shchesnyak-d/hpi-harvester) — it runs
`traktexport export <user>` on cron and drops snapshots into a well-known
layout that every HPI module in this repo can pick up automatically.

### Step 1. Produce a snapshot

Any of these layouts works — the module reads them all via
[`my.harvester.snapshot()`](src/my/harvester.py):

```bash
# A — via hpi-harvester (recommended: one data root for everything)
<harvester-root>/
└── trakt/
    ├── 2024-03-15T03-00-00.json
    ├── 2024-04-06T03-00-00.json
    └── _index.json

# B — a classic karlicoss/HPI glob
~/data/trakt/
├── trakt-2024-03-15.json
└── trakt-2024-04-06.json
```

For layout (A), see `hpi-harvester`'s README — you set it up once, and it
produces timestamped JSON snapshots on whatever schedule you like. For layout
(B), just run `traktexport export <user> > ~/data/trakt/<date>.json` yourself.

Either way, **the module always consumes the most recent snapshot**. Old
snapshots are kept around so cachew can notice when a new one lands.

### Step 2. Configure `my.config` <a id="step-2-configure-myconfig-trakt"></a>

Pick one of the two shapes, depending on which layout you went with above:

```python
# ~/.config/my/my/config/__init__.py

# Layout A — harvester-powered (shared root for every HPI module)
class harvester:
    root = '/path/to/hpi-harvester/data'

# Layout B — classic glob (you produce the JSON yourself)
class trakt:
    export_path = '~/data/trakt/*.json'
```

If your harvester YAML renames the exporter (e.g. `name: trakt_mine`), point
the module at that name explicitly:

```python
class trakt:
    harvester_name = 'trakt_mine'
```

### Step 3. Verify the setup <a id="step-3-verify-the-setup-trakt"></a>

```bash
hpi doctor my.trakt.export
hpi doctor my.trakt.all
```

Expected output:

```
✅  OK  : my.trakt.export
        - history   : 4217
        - ratings   : 812
        - watchlist : 94
        - likes     : 13
        - followers : 3
        - following : 5
```

As with the Letterboxd module, debug logging is opt-in:

```bash
LOGGING_LEVEL_my_trakt=debug hpi doctor my.trakt.export
```

### Public API (`my.trakt`)

```python
# Low-level source (reads the latest traktexport dump):
from my.trakt import export

export.history()        # Iterator[Res[HistoryEntry]]  — every watch event
export.ratings()        # Iterator[Res[Rating]]        — your ratings
export.watchlist()      # Iterator[Res[WatchListEntry]]
export.likes()          # Iterator[Res[Like]]          — liked lists + comments
export.followers()      # Iterator[Res[Follow]]
export.following()      # Iterator[Res[Follow]]
export.profile_stats()  # dict[str, Any]               — raw Trakt stats blob
export.export()         # FullTraktExport              — one-shot typed bundle
export.inputs()         # Sequence[Path]               — discovered snapshots

# The combined "facade" — preferred entry point for end-user scripts:
from my.trakt.all import (
    history, ratings, watchlist, likes, followers, following, profile_stats,
)
```

As in every HPI module, `Res[T]` is `T | Exception` — one broken row never
kills the stream.

### Domain model (`my.trakt.common`)

Every type is a frozen dataclass. Media-carrying entities form a small tagged
union — the string `media_type` tells you which concrete class is in
`media_data`.

```python
@dataclass(frozen=True, slots=True)
class SiteIds:
    trakt_id: int
    trakt_slug: str | None = None
    imdb_id: str | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    tvrage_id: int | None = None

@dataclass(frozen=True, slots=True)
class Movie:   title: str; year: int | None; ids: SiteIds
@dataclass(frozen=True, slots=True)
class Show:    title: str; year: int | None; ids: SiteIds
@dataclass(frozen=True, slots=True)
class Season:  season: int; ids: SiteIds; show: Show
@dataclass(frozen=True, slots=True)
class Episode: title: str | None; season: int; episode: int; ids: SiteIds; show: Show

@dataclass(frozen=True, slots=True)
class HistoryEntry:
    history_id: int
    watched_at: datetime
    action: str                              # 'scrobble' | 'watch' | 'checkin' | …
    media_type: Literal['movie', 'episode']
    media_data: Movie | Episode

@dataclass(frozen=True, slots=True)
class Rating:
    rated_at: datetime
    rating: int                              # 1..10
    media_type: Literal['movie', 'show', 'season', 'episode']
    media_data: Movie | Show | Season | Episode

@dataclass(frozen=True, slots=True)
class WatchListEntry:
    listed_at: datetime
    listed_at_id: int
    media_type: Literal['movie', 'show']
    media_data: Movie | Show

@dataclass(frozen=True, slots=True)
class Like:
    liked_at: datetime
    media_type: Literal['list', 'comment']
    media_data: TraktList | Comment

@dataclass(frozen=True, slots=True)
class Follow: followed_at: datetime; username: str
```

### Usage examples (`my.trakt`)

#### Watch history by weekday

```python
from collections import Counter
from my.trakt.all import history

days = Counter(
    e.watched_at.strftime('%A')
    for e in history()
    if not isinstance(e, Exception)
)
for day, count in days.most_common():
    print(f"{day:<10}  {count}")
```

#### Top-rated shows

```python
from my.trakt.all import ratings
from my.trakt.common import Show

top_shows = sorted(
    (r for r in ratings() if not isinstance(r, Exception) and isinstance(r.media_data, Show)),
    key=lambda r: (r.rating, r.rated_at),
    reverse=True,
)
for r in top_shows[:10]:
    print(f"{r.rating:>2}  {r.media_data.title} ({r.media_data.year})")
```

#### Things I still want to watch, grouped by type

```python
from collections import defaultdict
from my.trakt.all import watchlist

by_type: dict[str, list[str]] = defaultdict(list)
for w in watchlist():
    if isinstance(w, Exception):
        continue
    by_type[w.media_type].append(w.media_data.title)

for kind, titles in by_type.items():
    print(f"{kind.upper()}  ({len(titles)})")
    for t in titles:
        print(f"  - {t}")
```

#### Cross-source: Letterboxd diary meets Trakt ratings

Trakt carries `imdb` / `tmdb` ids out of the box, which makes it trivial to
join with any other source that also knows IMDB ids:

```python
from my.letterboxd.all import diary
from my.trakt.all import ratings
from my.trakt.common import Movie

trakt_by_imdb = {
    r.media_data.ids.imdb_id: r.rating
    for r in ratings()
    if not isinstance(r, Exception) and isinstance(r.media_data, Movie)
}
# …match against Letterboxd entries via film.slug / film.uri
```

---

## CLI: `hpi query`

HPI ships with a built-in JSON query interface — no code required:

```bash
# the most recent diary entries:
hpi query my.letterboxd.all.diary --order-type datetime --limit 5

# dump every review as JSONL (handy for full-text indexing):
hpi query my.letterboxd.all.reviews --stream > reviews.jsonl

# watchlist items added in the last year:
hpi query my.letterboxd.all.watchlist --order-type datetime --recent 365d

# last ten Trakt watch events:
hpi query my.trakt.all.history --order-type datetime --limit 10

# all Trakt ratings of 10, streamed as JSONL:
hpi query my.trakt.all.ratings --stream | jq 'select(.rating == 10)'
```

---

## Caching (cachew)

If `cachew` is installed (`pip install -e ".[cache]"`), the per-entity streams
are cached automatically:

- Letterboxd: `diary()`, `ratings()`, `watched()`, `watchlist()`, `reviews()`,
  `likes()`.
- Trakt: `history()`, `ratings()`, `likes()`, `followers()`, `following()`.
  `watchlist()` is intentionally *not* cached — it's tiny and its tagged-union
  shape trips cachew's schema inference, matching the same decision in
  [`purarue/HPI`](https://github.com/purarue/HPI).

The cache is invalidated based on the mtime of every path in `inputs()`, so
dropping in a fresh export rebuilds the cache on the next call.

For where the cache lives and how to tune it, see
[HPI SETUP](https://github.com/karlicoss/HPI/blob/master/doc/SETUP.org).

---

## Logging

Logging goes through `my.core.make_logger`. The level is controlled by an
environment variable with the `LOGGING_LEVEL_` prefix and the module name
with dots replaced by underscores:

```bash
LOGGING_LEVEL_my_letterboxd=debug   hpi query my.letterboxd.all.diary
LOGGING_LEVEL_my_letterboxd=warning hpi doctor my.letterboxd.export
LOGGING_LEVEL_my_trakt=debug        hpi query my.trakt.all.history
```

---

## Development

For day-to-day development a regular virtualenv is the most convenient choice
(IDE integrations, faster iteration, no isolation tax):

```bash
# environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[cache,tests,dev]"

# linter
ruff check .
ruff format .

# types
mypy

# tests (CSV fixtures live under testdata/)
pytest
```

If you prefer [`uv`](https://docs.astral.sh/uv/), the equivalent is:

```bash
uv venv
uv pip install -e ".[cache,tests,dev]"
```

CI runs all of the above for Python 3.10–3.13 on Linux and macOS — see
[.github/workflows/ci.yml](.github/workflows/ci.yml).

### Project layout

```
.
├── pyproject.toml
├── README.md
├── src/
│   └── my/                          # namespace package (no __init__.py here!)
│       ├── harvester.py             # shared snapshot discovery helper
│       ├── letterboxd/
│       │   ├── __init__.py
│       │   ├── common.py            # models + helpers (CSV / ZIP)
│       │   ├── export.py            # parser of the official export
│       │   ├── all.py               # facade for plugging in extra sources
│       │   └── py.typed
│       └── trakt/
│           ├── __init__.py
│           ├── common.py            # dataclasses + JSON parsers
│           ├── export.py            # harvester-driven source
│           ├── all.py               # facade for plugging in extra sources
│           └── py.typed
├── tests/
│   ├── conftest.py                  # fixtures with a fake my.config.letterboxd
│   ├── test_common.py               # unit tests for value parsers
│   ├── test_export.py               # integration tests for CSV/ZIP
│   ├── test_harvester.py            # snapshot-discovery helper
│   └── test_trakt.py                # my.trakt unit + integration tests
├── testdata/
│   ├── letterboxd-export-sample/    # small but realistic CSV/ZIP
│   └── trakt-export-sample.json     # realistic Trakt dump
└── .github/workflows/ci.yml
```

---

## Adding new modules to this repository

The structure is designed to grow — e.g. so that Spotify, Goodreads, Kinopoisk
etc. can sit next to Letterboxd. The recipe:

1. Create a sub-package under `src/my/<servicename>/`. Minimum:

   ```
   src/my/<servicename>/
   ├── __init__.py        # docstring + __all__
   ├── common.py          # domain models and low-level helpers
   ├── <source>.py        # one or more data sources
   └── all.py             # facade with import_source(...)
   ```

2. Follow the same conventions as `letterboxd`:

   - configure via a `Protocol` + `make_config()` on top of
     `my.config.<servicename>`;
   - public functions return `Iterator[Res[T]]` and don't blow up on a single
     bad row;
   - domain types are `@dataclass(frozen=True, slots=True)`;
   - cache via `from my.core.cachew import mcachew` with `depends_on=inputs`;
   - log via `my.core.make_logger(__name__)`;
   - expose a `stats()` function for `hpi doctor`.

3. Drop a small but realistic data sample under `testdata/<servicename>/`
   and write tests like `tests/test_export.py`.

4. Update the README — add a row to the modules table and a setup section.

5. The CI matrix is already set up — it'll automatically run ruff, mypy and
   pytest against the new module on every push.

For a deeper dive into HPI module design and extensibility, see
[doc/MODULE_DESIGN.org](https://github.com/karlicoss/HPI/blob/master/doc/MODULE_DESIGN.org)
in the upstream repository.

---

## License

[MIT](LICENSE).
