"""
Parser for the `purarue/traktexport`_ JSON dump.

Each successful ``traktexport export <username>`` run is one snapshot — a
single JSON file holding the full account state (history, ratings,
watchlist, likes, followers, stats, profile settings). This module finds the
latest snapshot via :mod:`my.harvester` and yields typed dataclasses from
:mod:`my.trakt.common`.

Expected configuration (``~/.config/my/my/config/__init__.py``). Pick one:

.. code-block:: python

    # 1. Harvester-powered (recommended — lets every HPI module share the
    #    same data root):
    class harvester:
        root = '/path/to/hpi-harvester/data'

    # 2. Classic karlicoss/HPI shape (useful if you keep manual exports):
    class trakt:
        export_path = '~/data/trakt/*.json'

    # 3. Rename the exporter in the harvester YAML? Override the source name:
    class trakt:
        harvester_name = 'trakt_mine'

Self-check::

    hpi doctor my.trakt.export

.. _purarue/traktexport: https://github.com/purarue/traktexport
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from my.core import Res, Stats, make_logger, stat
from my.harvester import snapshot

from .common import (
    Follow,
    FullTraktExport,
    HistoryEntry,
    Like,
    Rating,
    TraktParseError,
    WatchListEntry,
    parse_export,
    parse_follow,
    parse_history_entry,
    parse_like,
    parse_rating,
    parse_watchlist_entry,
)

logger = make_logger(__name__)


# The harvester source name. Users may override via
# ``my.config.trakt.harvester_name`` — that's resolved inside
# :func:`my.harvester.snapshot`.
_DEFAULT_SOURCE = "trakt"


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------


def inputs() -> Sequence[Path]:
    """Every Trakt snapshot known to the harvester, sorted ascending.

    Returns an empty list if no snapshot has been produced yet — callers
    downstream raise :class:`FileNotFoundError` with a more actionable
    message when they try to parse.
    """
    snap = snapshot(
        source=_DEFAULT_SOURCE,
        module="trakt",
        extensions=(".json",),
    )
    return snap.all()


def _latest() -> Path:
    """The freshest ``traktexport`` snapshot on disk."""
    snap = snapshot(
        source=_DEFAULT_SOURCE,
        module="trakt",
        extensions=(".json",),
    )
    latest = snap.latest()
    logger.info(f"using latest Trakt snapshot: {latest}")
    return latest


# ---------------------------------------------------------------------------
# Cachew (optional). The module works without cachew installed.
# ---------------------------------------------------------------------------

try:
    from my.core.cachew import mcachew
except ImportError:  # pragma: no cover - cachew is optional
    from collections.abc import Callable
    from typing import TypeVar

    _F = TypeVar("_F", bound=Callable[..., Any])

    def mcachew(*_args: Any, **_kwargs: Any) -> Callable[[_F], _F]:  # type: ignore[no-redef]
        def decorator(fn: _F) -> _F:
            return fn

        return decorator


def _cache_key() -> list[float]:
    """mtime-based cache key for cachew.

    Equivalent of the pattern used in ``purarue/HPI``'s ``my.trakt.export``:
    whenever any snapshot file changes, every cached stream is invalidated.
    """
    return [p.lstat().st_mtime for p in sorted(inputs())]


# ---------------------------------------------------------------------------
# Raw dump loader (not cached on purpose — cheap vs. the disk + network cost
# ``cachew`` brings, since we already cache each typed stream below)
# ---------------------------------------------------------------------------


def _load_latest_raw() -> dict[str, Any]:
    """Read and JSON-parse the latest snapshot on disk."""
    with _latest().open(encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        raise TraktParseError(
            f"expected a JSON object at the root of the snapshot, got {type(data).__name__}"
        )
    return data


def export() -> FullTraktExport:
    """Return the fully-parsed latest snapshot as a :class:`FullTraktExport`.

    This is the convenience entry point for ad-hoc scripts — when you want
    both the aggregate ``stats`` dict *and* the typed streams in one shot
    without triggering multiple disk reads.
    """
    return parse_export(_load_latest_raw())


# ---------------------------------------------------------------------------
# Per-entity streams (the HPI convention — iterables of ``Res[T]``).
# ---------------------------------------------------------------------------


def _iter_entries(
    key: str,
    parser: Any,  # Callable[[dict], T] — but we want Res[T] at the call site.
) -> Iterator[Res[Any]]:
    """Iterate rows under ``key`` in the latest snapshot, wrapping errors."""
    raw = _load_latest_raw()
    rows = raw.get(key)
    if rows is None:
        return
    if not isinstance(rows, list):
        yield TraktParseError(
            f"expected a list under top-level key {key!r}, got {type(rows).__name__}"
        )
        return
    for idx, row in enumerate(rows):
        try:
            yield parser(row)
        except Exception as e:
            logger.exception(f"failed to parse {key} row {idx}: {row!r}")
            yield e


@mcachew(depends_on=_cache_key)
def history() -> Iterator[Res[HistoryEntry]]:
    """Every watched event (movies + episodes), chronologically via Trakt."""
    yield from _iter_entries("history", parse_history_entry)


@mcachew(depends_on=_cache_key)
def ratings() -> Iterator[Res[Rating]]:
    """Ratings (movies / shows / seasons / episodes)."""
    yield from _iter_entries("ratings", parse_rating)


# Not cached: the watchlist is always tiny, and cachew on iterators of
# tagged-union dataclasses is fiddly. Mirrors the same decision in
# ``purarue/HPI``.
def watchlist() -> Iterator[Res[WatchListEntry]]:
    """Films and shows queued to watch later."""
    yield from _iter_entries("watchlist", parse_watchlist_entry)


@mcachew(depends_on=_cache_key)
def likes() -> Iterator[Res[Like]]:
    """Liked lists and liked comments."""
    yield from _iter_entries("likes", parse_like)


@mcachew(depends_on=_cache_key)
def followers() -> Iterator[Res[Follow]]:
    """Users who follow this account."""
    yield from _iter_entries("followers", parse_follow)


@mcachew(depends_on=_cache_key)
def following() -> Iterator[Res[Follow]]:
    """Users this account follows."""
    yield from _iter_entries("following", parse_follow)


def profile_stats() -> dict[str, Any]:
    """The raw ``stats`` dict from the snapshot — aggregate counts by Trakt itself.

    Returned as-is (plain dict). It's never large (<1 KB) and the schema is
    too loose for useful dataclass modelling — Trakt ships a couple dozen
    nested counters (``{"movies": {"plays": ..., "watched": ...}, ...}``).
    """
    return dict(_load_latest_raw().get("stats") or {})


# ---------------------------------------------------------------------------
# Stats for `hpi doctor`
# ---------------------------------------------------------------------------


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
    "export",
    "followers",
    "following",
    "history",
    "inputs",
    "likes",
    "profile_stats",
    "ratings",
    "stats",
    "watchlist",
]
