"""
Combined data source for ps-timetracker.

Currently a thin proxy over :mod:`my.ps_timetracker.export` — there is a
single source today. The facade exists so that future sources (an official
PSN API client, a companion scraper) can plug in via ``import_source``
without changing the public entry points.

Usage::

    from my.ps_timetracker.all import sessions, library

    for s in sessions():
        if isinstance(s, Exception):
            continue
        print(s.start_local, s.game_title, s.duration)

    snap = library()
    print(snap.fetched_at_utc, len(snap.games))
"""

from __future__ import annotations

from collections.abc import Iterator

from my.core import Res, Stats, stat
from my.core.source import import_source

from .common import Library, Session

_export_src = import_source(module_name="my.ps_timetracker.export")


@_export_src
def _export_sessions() -> Iterator[Res[Session]]:
    from . import export

    yield from export.sessions()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def sessions() -> Iterator[Res[Session]]:
    yield from _export_sessions()


def library() -> Library:
    """Non-iterable passthrough — the latest library snapshot."""
    from . import export

    return export.library()


def stats() -> Stats:
    return {
        **stat(sessions),
        "library": len(library().games),
    }


__all__ = [
    "library",
    "sessions",
    "stats",
]
