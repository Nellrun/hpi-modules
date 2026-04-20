"""
Parser for the official `Letterboxd <https://letterboxd.com>`_ ZIP export.

Letterboxd lets users download a ZIP archive of all their content from
Settings → Data: diary, ratings, watchlist, reviews, likes, etc. This module
operates on top of such archives (or their unpacked directories) and yields
typed dataclasses.

Expected configuration (``~/.config/my/my/config/__init__.py``)::

    class letterboxd:
        # Anything understood by ``my.core.get_files`` works: a path, a glob,
        # or a list. Both directories and ZIP archives are supported.
        export_path = '~/data/letterboxd/letterboxd-username-*.zip'

Self-check::

    hpi doctor my.letterboxd.export
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator, Sequence
from glob import glob
from pathlib import Path
from typing import Protocol

from my.core import Paths, Res, Stats, make_logger, stat

from .common import (
    DIARY_CSV,
    LIKES_FILMS_CSV,
    RATINGS_CSV,
    REVIEWS_CSV,
    WATCHED_CSV,
    WATCHLIST_CSV,
    Diary,
    Film,
    LetterboxdParseError,
    Like,
    Rating,
    Review,
    Watch,
    WatchlistItem,
    is_zip,
    make_film,
    open_csv,
    parse_bool_yes,
    parse_date,
    parse_rating,
    parse_tags,
)

logger = make_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class config(Protocol):
    """Structural protocol for the module's configuration.

    Concrete user configs are declared in ``my.config.letterboxd`` and mixed
    in via :func:`make_config` below.
    """

    @property
    @abstractmethod
    def export_path(self) -> Paths:
        """Path(s) to a ZIP archive (or directories with an unpacked export)."""
        raise NotImplementedError


def make_config() -> config:
    from my.config import letterboxd as user_config  # type: ignore[attr-defined]

    class combined_config(user_config, config):  # type: ignore[misc]
        ...

    return combined_config()


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------


def inputs() -> Sequence[Path]:
    """
    List of available exports, sorted ascending (the freshest comes last).

    Unlike ``my.core.get_files``, we treat a directory as **one** snapshot
    (an unpacked export) instead of expanding it into the files it contains.
    That matches Letterboxd semantics: every export is an independent atomic
    archive.
    """
    cfg = make_config()
    raw = cfg.export_path

    items: list[str | Path] = [raw] if isinstance(raw, (str, Path)) else list(raw)

    candidates: list[Path] = []
    for item in items:
        path = Path(item).expanduser()
        if path.exists():
            candidates.append(path)
            continue
        # the path doesn't exist as-is — try interpreting it as a glob
        for matched in glob(str(path)):
            candidates.append(Path(matched))

    valid = [p for p in candidates if p.is_dir() or is_zip(p)]
    return sorted(valid)


def _latest() -> Path:
    """
    Return the freshest export.

    A Letterboxd export is a complete snapshot, so the latest copy is enough.
    If you need a different strategy (e.g. merge multiple exports), use
    :func:`inputs` and your own wrapper.
    """
    sources = list(inputs())
    if not sources:
        raise FileNotFoundError(
            "my.letterboxd.export: no exports were found at export_path. "
            "Check the my.config.letterboxd.export_path setting."
        )
    latest = max(sources)
    logger.info(f"using latest Letterboxd export: {latest}")
    return latest


# ---------------------------------------------------------------------------
# Cachew (optional). If cachew is missing, parsing simply isn't cached.
# ---------------------------------------------------------------------------

try:
    from my.core.cachew import mcachew
except ImportError:  # pragma: no cover - cachew is optional
    from collections.abc import Callable
    from typing import Any, TypeVar

    _F = TypeVar("_F", bound=Callable[..., Any])

    def mcachew(*_args: Any, **_kwargs: Any) -> Callable[[_F], _F]:  # type: ignore[no-redef]
        def decorator(fn: _F) -> _F:
            return fn

        return decorator


# ---------------------------------------------------------------------------
# Per-file parsing
# ---------------------------------------------------------------------------


def _parse_diary_row(row: dict[str, str], *, with_review: bool) -> Diary:
    logged = parse_date(row["Date"])
    if logged is None:
        raise LetterboxdParseError(f"empty Date in diary/review row: {row!r}")
    return Diary(
        film=make_film(row),
        logged_date=logged,
        watched_date=parse_date(row.get("Watched Date", "")),
        rating=parse_rating(row.get("Rating", "")),
        rewatch=parse_bool_yes(row.get("Rewatch", "")),
        tags=parse_tags(row.get("Tags", "")),
        review=(row.get("Review", "").strip() or None) if with_review else None,
    )


# ---------------------------------------------------------------------------
# Public source functions
# ---------------------------------------------------------------------------


@mcachew(depends_on=inputs)
def diary() -> Iterator[Res[Diary]]:
    """Diary entries (enriched with reviews when they are available)."""
    src = _latest()

    # Pull reviews into memory once: there are usually far fewer of them than
    # diary entries, and an index by (uri, watched_date, logged_date) gives
    # O(1) enrichment.
    review_index: dict[tuple[str, str, str], str] = {}
    for row in open_csv(src, REVIEWS_CSV):
        text = row.get("Review", "").strip()
        if not text:
            continue
        key = (
            row.get("Letterboxd URI", "").strip(),
            row.get("Watched Date", "").strip(),
            row.get("Date", "").strip(),
        )
        review_index[key] = text

    for idx, row in enumerate(open_csv(src, DIARY_CSV)):
        try:
            entry = _parse_diary_row(row, with_review=False)
        except Exception as e:
            logger.exception(f"failed to parse diary row {idx}: {row!r}")
            yield e
            continue

        key = (
            entry.film.uri,
            row.get("Watched Date", "").strip(),
            row.get("Date", "").strip(),
        )
        review_text = review_index.get(key)
        if review_text is not None:
            entry = Diary(
                film=entry.film,
                logged_date=entry.logged_date,
                watched_date=entry.watched_date,
                rating=entry.rating,
                rewatch=entry.rewatch,
                tags=entry.tags,
                review=review_text,
            )
        yield entry


@mcachew(depends_on=inputs)
def reviews() -> Iterator[Res[Review]]:
    """Diary entries that have a non-empty review text."""
    src = _latest()
    for idx, row in enumerate(open_csv(src, REVIEWS_CSV)):
        try:
            d = _parse_diary_row(row, with_review=True)
            if d.review is None:
                # Shouldn't happen in practice, but defend against junk rows.
                continue
            yield Review.from_diary(d)
        except Exception as e:
            logger.exception(f"failed to parse review row {idx}: {row!r}")
            yield e


@mcachew(depends_on=inputs)
def ratings() -> Iterator[Res[Rating]]:
    """Current ratings for films (the latest rating per film)."""
    src = _latest()
    for idx, row in enumerate(open_csv(src, RATINGS_CSV)):
        try:
            r = parse_rating(row.get("Rating", ""))
            d = parse_date(row["Date"])
            if r is None or d is None:
                raise LetterboxdParseError(f"missing rating or date: {row!r}")
            yield Rating(film=make_film(row), rating=r, date=d)
        except Exception as e:
            logger.exception(f"failed to parse rating row {idx}: {row!r}")
            yield e


@mcachew(depends_on=inputs)
def watched() -> Iterator[Res[Watch]]:
    """Every film marked as watched (no rating/review)."""
    src = _latest()
    for idx, row in enumerate(open_csv(src, WATCHED_CSV)):
        try:
            d = parse_date(row["Date"])
            if d is None:
                raise LetterboxdParseError(f"missing date: {row!r}")
            yield Watch(film=make_film(row), date=d)
        except Exception as e:
            logger.exception(f"failed to parse watched row {idx}: {row!r}")
            yield e


@mcachew(depends_on=inputs)
def watchlist() -> Iterator[Res[WatchlistItem]]:
    """Films added to the watchlist (planned to watch)."""
    src = _latest()
    for idx, row in enumerate(open_csv(src, WATCHLIST_CSV)):
        try:
            d = parse_date(row["Date"])
            if d is None:
                raise LetterboxdParseError(f"missing date: {row!r}")
            yield WatchlistItem(film=make_film(row), date=d)
        except Exception as e:
            logger.exception(f"failed to parse watchlist row {idx}: {row!r}")
            yield e


@mcachew(depends_on=inputs)
def likes() -> Iterator[Res[Like]]:
    """Liked films (the ``likes/films.csv`` entry in the export)."""
    src = _latest()
    for idx, row in enumerate(open_csv(src, LIKES_FILMS_CSV)):
        try:
            d = parse_date(row["Date"])
            if d is None:
                raise LetterboxdParseError(f"missing date: {row!r}")
            yield Like(film=make_film(row), date=d)
        except Exception as e:
            logger.exception(f"failed to parse like row {idx}: {row!r}")
            yield e


def films() -> Iterator[Film]:
    """Every unique film mentioned anywhere in the export (keyed by `Letterboxd URI`)."""
    seen: set[str] = set()

    def _all_films() -> Iterator[Film]:
        for entry in diary():
            if not isinstance(entry, Exception):
                yield entry.film
        for r in ratings():
            if not isinstance(r, Exception):
                yield r.film
        for w in watched():
            if not isinstance(w, Exception):
                yield w.film
        for wl in watchlist():
            if not isinstance(wl, Exception):
                yield wl.film
        for lk in likes():
            if not isinstance(lk, Exception):
                yield lk.film

    for film in _all_films():
        if film.uri in seen:
            continue
        seen.add(film.uri)
        yield film


# ---------------------------------------------------------------------------
# Stats for `hpi doctor`
# ---------------------------------------------------------------------------


def stats() -> Stats:
    return {
        **stat(diary),
        **stat(reviews),
        **stat(ratings),
        **stat(watched),
        **stat(watchlist),
        **stat(likes),
    }


__all__ = [
    "config",
    "diary",
    "films",
    "inputs",
    "likes",
    "make_config",
    "ratings",
    "reviews",
    "stats",
    "watched",
    "watchlist",
]
