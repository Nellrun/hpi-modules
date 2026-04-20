"""
Combined data source for Letterboxd.

Design rationale (see ``doc/MODULE_DESIGN.org`` in karlicoss/HPI): when a
single "service" gains multiple ways of producing data (official export,
RSS feed, scraper, unofficial API), each source lives in its own module and
``all.py`` becomes a thin facade that stitches them together.

Today there is just one source — :mod:`my.letterboxd.export`. As new ones
appear (e.g. ``my.letterboxd.rss`` for recently watched films, or
``my.letterboxd.scraper`` for the social graph) it is enough to register
them here through ``import_source``: that automatically gives soft
degradation (if a user hasn't configured a source, you get a warning rather
than a crash).

Usage examples::

    from my.letterboxd.all import diary, ratings, watched

    # Most recent diary entries:
    for entry in sorted(
        (e for e in diary() if not isinstance(e, Exception)),
        key=lambda e: e.logged_date,
        reverse=True,
    )[:10]:
        print(entry.logged_date, entry.film.name, entry.rating)
"""

from __future__ import annotations

from collections.abc import Iterator

from my.core import Res, Stats, stat
from my.core.source import import_source

from .common import Diary, Like, Rating, Review, Watch, WatchlistItem

# ---------------------------------------------------------------------------
# Registered sources
# ---------------------------------------------------------------------------

_export_src = import_source(module_name="my.letterboxd.export")


@_export_src
def _export_diary() -> Iterator[Res[Diary]]:
    from . import export

    yield from export.diary()


@_export_src
def _export_reviews() -> Iterator[Res[Review]]:
    from . import export

    yield from export.reviews()


@_export_src
def _export_ratings() -> Iterator[Res[Rating]]:
    from . import export

    yield from export.ratings()


@_export_src
def _export_watched() -> Iterator[Res[Watch]]:
    from . import export

    yield from export.watched()


@_export_src
def _export_watchlist() -> Iterator[Res[WatchlistItem]]:
    from . import export

    yield from export.watchlist()


@_export_src
def _export_likes() -> Iterator[Res[Like]]:
    from . import export

    yield from export.likes()


# ---------------------------------------------------------------------------
# Combined public functions
# ---------------------------------------------------------------------------
#
# Right now there's a single source, so the functions just proxy. Once more
# sources show up, the merging logic (e.g. dedup by (uri, date)) lives here.
# The public signatures stay the same.


def diary() -> Iterator[Res[Diary]]:
    yield from _export_diary()


def reviews() -> Iterator[Res[Review]]:
    yield from _export_reviews()


def ratings() -> Iterator[Res[Rating]]:
    yield from _export_ratings()


def watched() -> Iterator[Res[Watch]]:
    yield from _export_watched()


def watchlist() -> Iterator[Res[WatchlistItem]]:
    yield from _export_watchlist()


def likes() -> Iterator[Res[Like]]:
    yield from _export_likes()


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
    "diary",
    "likes",
    "ratings",
    "reviews",
    "stats",
    "watched",
    "watchlist",
]
