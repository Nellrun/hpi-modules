"""
Combined data source for Trakt.

Currently a thin proxy over :mod:`my.trakt.export` — there is a single
source today. The facade exists so that future sources (a live Trakt API
client, a scraper, a companion export from Serializd or Letterboxd) can
plug in via ``import_source`` without changing the public entry points.

Usage::

    from my.trakt.all import history, ratings, watchlist

    for entry in history():
        if isinstance(entry, Exception):
            continue
        print(entry.watched_at, entry.media_data)
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from my.core import Res, Stats, stat
from my.core.source import import_source

from .common import Follow, HistoryEntry, Like, Rating, WatchListEntry

_export_src = import_source(module_name="my.trakt.export")


@_export_src
def _export_history() -> Iterator[Res[HistoryEntry]]:
    from . import export

    yield from export.history()


@_export_src
def _export_ratings() -> Iterator[Res[Rating]]:
    from . import export

    yield from export.ratings()


@_export_src
def _export_watchlist() -> Iterator[Res[WatchListEntry]]:
    from . import export

    yield from export.watchlist()


@_export_src
def _export_likes() -> Iterator[Res[Like]]:
    from . import export

    yield from export.likes()


@_export_src
def _export_followers() -> Iterator[Res[Follow]]:
    from . import export

    yield from export.followers()


@_export_src
def _export_following() -> Iterator[Res[Follow]]:
    from . import export

    yield from export.following()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def history() -> Iterator[Res[HistoryEntry]]:
    yield from _export_history()


def ratings() -> Iterator[Res[Rating]]:
    yield from _export_ratings()


def watchlist() -> Iterator[Res[WatchListEntry]]:
    yield from _export_watchlist()


def likes() -> Iterator[Res[Like]]:
    yield from _export_likes()


def followers() -> Iterator[Res[Follow]]:
    yield from _export_followers()


def following() -> Iterator[Res[Follow]]:
    yield from _export_following()


def profile_stats() -> dict[str, Any]:
    """Non-iterable passthrough — Trakt's aggregate profile stats dict."""
    from . import export

    return export.profile_stats()


def stats() -> Stats:
    return {
        **stat(history),
        **stat(ratings),
        **stat(watchlist),
        **stat(likes),
        **stat(followers),
        **stat(following),
    }


__all__ = [
    "followers",
    "following",
    "history",
    "likes",
    "profile_stats",
    "ratings",
    "stats",
    "watchlist",
]
