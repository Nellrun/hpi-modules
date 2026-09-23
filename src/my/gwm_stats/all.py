"""
Combined data source for the gwm-stats aggregator.

Currently a thin proxy over :mod:`my.gwm_stats.export` — there is a single
source today. The facade exists so future sources (e.g. a direct hit
against the aggregator API, or alternative archives) can plug in via
``import_source`` without changing the public entry points.

Usage::

    from my.gwm_stats.all import games, sessions, trophies, summary

    for s in sessions():
        if isinstance(s, Exception):
            continue
        print(s.started_at, s.title_name, s.duration)

    print(summary().totals.total_duration)
"""

from __future__ import annotations

from collections.abc import Iterator

from my.core import Res, Stats, stat
from my.core.source import import_source

from .common import Game, Session, Summary, Trophy

_export_src = import_source(module_name="my.gwm_stats.export")


@_export_src
def _export_sessions() -> Iterator[Res[Session]]:
    from . import export

    yield from export.sessions()


@_export_src
def _export_trophies() -> Iterator[Res[Trophy]]:
    from . import export

    yield from export.trophies()


def sessions() -> Iterator[Res[Session]]:
    yield from _export_sessions()


def trophies() -> Iterator[Res[Trophy]]:
    yield from _export_trophies()


def games() -> Iterator[Game]:
    from . import export

    yield from export.games()


def summary() -> Summary:
    from . import export

    return export.summary()


def stats() -> Stats:
    return {
        **stat(sessions),
        **stat(trophies),
    }


__all__ = [
    "games",
    "sessions",
    "stats",
    "summary",
    "trophies",
]
