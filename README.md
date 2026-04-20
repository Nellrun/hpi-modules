# hpi-modules

Additional modules for [karlicoss/HPI](https://github.com/karlicoss/HPI) — the
Human Programming Interface, a Python package (`my`) that turns your scattered
"digital life" into ordinary Python objects.

Currently shipping:

| Module                         | Description                                                              |
| ------------------------------ | ------------------------------------------------------------------------ |
| [`my.letterboxd`](#letterboxd) | Diary entries, ratings, reviews, watchlist and likes from Letterboxd     |

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

### Option 1. On top of an existing HPI install (recommended)

```bash
# 1. HPI itself
pip install --user HPI

# 2. this package (editable, so you can keep adding modules easily)
git clone https://github.com/<your-fork>/hpi-modules.git
cd hpi-modules
pip install --user -e .
```

`pip install -e .` will pull in all dependencies (including `HPI`) and install
the package in editable mode, so any change you make under
`src/my/letterboxd/*.py` is picked up immediately.

### Option 2. With all the batteries

```bash
pip install --user -e ".[cache,tests,dev]"
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

## CLI: `hpi query`

HPI ships with a built-in JSON query interface — no code required:

```bash
# the most recent diary entries:
hpi query my.letterboxd.all.diary --order-type datetime --limit 5

# dump every review as JSONL (handy for full-text indexing):
hpi query my.letterboxd.all.reviews --stream > reviews.jsonl

# watchlist items added in the last year:
hpi query my.letterboxd.all.watchlist --order-type datetime --recent 365d
```

---

## Caching (cachew)

If `cachew` is installed (`pip install -e ".[cache]"`), the
`diary()`, `ratings()`, `watched()`, `watchlist()`, `reviews()` and `likes()`
functions are cached automatically. The cache is invalidated based on the
contents of `inputs()`, so dropping in a fresh export will rebuild the cache
on the next call.

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
```

---

## Development

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

CI runs all of the above for Python 3.10–3.13 on Linux and macOS — see
[.github/workflows/ci.yml](.github/workflows/ci.yml).

### Project layout

```
.
├── pyproject.toml
├── README.md
├── src/
│   └── my/                          # namespace package (no __init__.py here!)
│       └── letterboxd/
│           ├── __init__.py
│           ├── common.py            # models + helpers (CSV / ZIP)
│           ├── export.py            # parser of the official export
│           ├── all.py               # facade for plugging in extra sources
│           └── py.typed
├── tests/
│   ├── conftest.py                  # fixtures with a fake my.config.letterboxd
│   ├── test_common.py               # unit tests for value parsers
│   └── test_export.py               # integration tests for CSV/ZIP
├── testdata/
│   └── letterboxd-export-sample/    # small but realistic export
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
