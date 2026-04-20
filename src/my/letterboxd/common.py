"""
Shared domain models and low-level helpers for the Letterboxd modules.

Defines domain types (``Film``, ``Diary``, ``Rating``, ``Watch``,
``WatchlistItem``, ``Like``, ``Review``) and helpers for reading CSV files
either from an unpacked export directory or directly from the ZIP archive
that Letterboxd hands out to users.

The models are intentionally "flat" and built from primitives — this gives
correct behaviour when serialising/caching with ``cachew`` and makes it easy
to consume the data with ``pandas``.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import IO, Final

# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Film:
    """Minimal identity record for a film on Letterboxd."""

    name: str
    year: int | None
    uri: str

    @property
    def slug(self) -> str:
        """Letterboxd slug (the last URI segment), handy for comparison/merging."""
        return self.uri.rstrip("/").rsplit("/", 1)[-1]


@dataclass(frozen=True, slots=True)
class Diary:
    """
    A diary entry for a single watch.

    Rating and review are optional.
    """

    film: Film
    logged_date: date
    """Date when the entry was created in the diary."""

    watched_date: date | None
    """Actual date the film was watched (if the user provided one)."""

    rating: float | None
    """Rating, 0.5 .. 5.0 in 0.5 steps; ``None`` means no rating was given."""

    rewatch: bool
    tags: tuple[str, ...] = field(default_factory=tuple)
    review: str | None = None


@dataclass(frozen=True, slots=True)
class Rating:
    """The user's current rating for a film (not tied to any specific watch)."""

    film: Film
    rating: float
    date: date


@dataclass(frozen=True, slots=True)
class Watch:
    """A "watched" mark (no rating/review attached)."""

    film: Film
    date: date


@dataclass(frozen=True, slots=True)
class WatchlistItem:
    """A film added to the watchlist."""

    film: Film
    date: date


@dataclass(frozen=True, slots=True)
class Like:
    """A "liked film" entry."""

    film: Film
    date: date


@dataclass(frozen=True, slots=True)
class Review(Diary):
    """
    A diary entry that has a non-empty review text.

    At the type level this is a ``Diary`` with ``review is not None`` (the
    invariant is enforced in :meth:`Review.from_diary`). Having a separate
    type is convenient for declarative filtering downstream.
    """

    @classmethod
    def from_diary(cls, d: Diary) -> Review:
        if d.review is None:
            raise ValueError("Review.from_diary called with empty review")
        return cls(
            film=d.film,
            logged_date=d.logged_date,
            watched_date=d.watched_date,
            rating=d.rating,
            rewatch=d.rewatch,
            tags=d.tags,
            review=d.review,
        )


# ---------------------------------------------------------------------------
# CSV field parsing
# ---------------------------------------------------------------------------


# Names of CSV files inside the Letterboxd export. Exposed as public constants
# so they can be reused (e.g. by tests or alternative sources).
DIARY_CSV: Final = "diary.csv"
RATINGS_CSV: Final = "ratings.csv"
WATCHED_CSV: Final = "watched.csv"
WATCHLIST_CSV: Final = "watchlist.csv"
REVIEWS_CSV: Final = "reviews.csv"
LIKES_FILMS_CSV: Final = "likes/films.csv"
PROFILE_CSV: Final = "profile.csv"


class LetterboxdParseError(ValueError):
    """Failure to parse a row of a Letterboxd export."""


def parse_date(value: str) -> date | None:
    """
    Parse a Letterboxd date (``YYYY-MM-DD``).

    Returns ``None`` for empty strings — this is valid for the
    ``Watched Date`` column on older diary entries.
    """
    value = value.strip()
    if not value:
        return None
    return date.fromisoformat(value)


def parse_datetime(value: str) -> datetime | None:
    """Parse a date-time stamp, when present in the file."""
    value = value.strip()
    if not value:
        return None
    # Letterboxd sometimes uses `YYYY-MM-DD HH:MM:SS`, sometimes ISO-8601.
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def parse_year(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    return int(value)


def parse_rating(value: str) -> float | None:
    """
    Parse a rating (``0.5`` .. ``5.0``).

    Returns ``None`` when there is no rating.
    """
    value = value.strip()
    if not value:
        return None
    try:
        rating = float(value)
    except ValueError as e:
        raise LetterboxdParseError(f"invalid rating: {value!r}") from e
    if not 0.0 < rating <= 5.0:
        raise LetterboxdParseError(f"rating out of range [0.5..5.0]: {rating}")
    return rating


def parse_bool_yes(value: str) -> bool:
    """Letterboxd uses ``Yes``/empty for boolean columns (e.g. ``Rewatch``)."""
    return value.strip().lower() == "yes"


def parse_tags(value: str) -> tuple[str, ...]:
    """Parse a comma-separated list of tags."""
    value = value.strip()
    if not value:
        return ()
    return tuple(t.strip() for t in value.split(",") if t.strip())


def make_film(row: dict[str, str]) -> Film:
    """Build a :class:`Film` from a CSV row. The columns are common to every export file."""
    return Film(
        name=row["Name"],
        year=parse_year(row.get("Year", "")),
        uri=row["Letterboxd URI"].strip(),
    )


# ---------------------------------------------------------------------------
# Reading the data source (directory or ZIP)
# ---------------------------------------------------------------------------


class UnsupportedSource(ValueError):
    """The source is neither a directory nor a valid ZIP archive."""


def is_zip(path: Path) -> bool:
    """Safe check: is the path an existing ZIP file?"""
    try:
        return path.is_file() and zipfile.is_zipfile(path)
    except OSError:
        return False


def open_csv(source: Path, name: str) -> Iterator[dict[str, str]]:
    """
    Iterate rows of the CSV file ``name`` inside ``source``.

    ``source`` can be either:

    * a directory holding an unpacked export — the file is looked up at
      ``source / name``;
    * a ZIP archive — the file is read straight from it (no extraction).

    If the file is missing the generator simply finishes without raising:
    that's a normal situation (e.g. a user without ``reviews.csv`` because
    they have never written a review).
    """
    if source.is_dir():
        path = source / name
        if not path.exists():
            return
        with path.open(newline="", encoding="utf-8-sig") as fp:
            yield from _iter_dict_rows(fp)
        return

    if is_zip(source):
        with zipfile.ZipFile(source) as zf:
            try:
                info = zf.getinfo(name)
            except KeyError:
                return
            with zf.open(info) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                yield from _iter_dict_rows(text)
        return

    raise UnsupportedSource(
        f"{source}: expected a directory holding a Letterboxd export or a ZIP archive"
    )


def _iter_dict_rows(stream: IO[str]) -> Iterator[dict[str, str]]:
    reader = csv.DictReader(stream)
    if reader.fieldnames is None:
        return
    for row in reader:
        # `csv.DictReader` may return None for missing columns. Normalise to
        # str so callers always work with a uniform type.
        yield {k: ("" if v is None else v) for k, v in row.items()}


__all__ = [
    "DIARY_CSV",
    "LIKES_FILMS_CSV",
    "PROFILE_CSV",
    "RATINGS_CSV",
    "REVIEWS_CSV",
    "WATCHED_CSV",
    "WATCHLIST_CSV",
    "Diary",
    "Film",
    "LetterboxdParseError",
    "Like",
    "Rating",
    "Review",
    "UnsupportedSource",
    "Watch",
    "WatchlistItem",
    "is_zip",
    "make_film",
    "open_csv",
    "parse_bool_yes",
    "parse_date",
    "parse_datetime",
    "parse_rating",
    "parse_tags",
    "parse_year",
]
