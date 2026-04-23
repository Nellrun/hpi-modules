"""
Parser for ``ps-timetracker-export`` snapshot directories.

Each ``ps-timetracker-export`` run produces a directory snapshot with:

* ``sessions.jsonl`` — one session per line (schema documented in
  :mod:`my.ps_timetracker.common`).
* ``library.json`` — per-game aggregates as of this run.
* ``meta.json`` — snapshot metadata (``fetched_at_utc``, ``profile``,
  incremental cursor, ...).
* ``raw/*.html`` — original HTML pages, kept for debugging.

Sessions are merged across every snapshot on disk, deduplicated by
``playtime_id``. Newer snapshots win: if the harvester re-scrapes a
playtime row after the user edits the session on ps-timetracker.com, the
edit lands in a later snapshot and supersedes the earlier version.

The library aggregate is read from the **latest** snapshot only — it is a
full rewrite every run, so historical merging would only duplicate data.

Expected configuration (``~/.config/my/my/config/__init__.py``). Pick one:

.. code-block:: python

    # 1. Harvester-powered (recommended):
    class harvester:
        root = '/path/to/hpi-harvester/data'

    # 2. Classic karlicoss/HPI shape — point at a directory that contains
    #    timestamped snapshot subdirectories in the harvester layout:
    class ps_timetracker:
        export_path = '~/data/ps_timetracker'

    # 3. Rename the exporter in the harvester YAML? Override the source name:
    class ps_timetracker:
        harvester_name = 'ps_timetracker_mine'

Self-check::

    hpi doctor my.ps_timetracker.export
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from my.core import Res, Stats, make_logger, stat
from my.harvester import snapshot

from .common import (
    Library,
    LibraryGame,
    PSTimetrackerParseError,
    Session,
    parse_library_game,
    parse_session,
)

logger = make_logger(__name__)


# The harvester source name. Users may override via
# ``my.config.ps_timetracker.harvester_name``.
_DEFAULT_SOURCE = "ps_timetracker"

_SESSIONS_FILENAME = "sessions.jsonl"
_LIBRARY_FILENAME = "library.json"
_META_FILENAME = "meta.json"


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------


def inputs() -> Sequence[Path]:
    """Every ps-timetracker snapshot directory known to the harvester.

    Sorted ascending (oldest → newest). Empty when no snapshot has been
    produced yet — downstream callers raise :class:`FileNotFoundError` with
    an actionable message.
    """
    # No ``extensions`` filter: the harvester writes *directories*, not single
    # files, so we want every timestamped child regardless of suffix.
    snap = snapshot(source=_DEFAULT_SOURCE, module="ps_timetracker")
    return snap.all()


def _latest() -> Path:
    """The freshest snapshot directory on disk."""
    snap = snapshot(source=_DEFAULT_SOURCE, module="ps_timetracker")
    latest = snap.latest()
    logger.info(f"using latest ps-timetracker snapshot: {latest}")
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


def _sessions_cache_key() -> list[tuple[str, float]]:
    """mtime key over every ``sessions.jsonl`` we might merge."""
    keys: list[tuple[str, float]] = []
    for snap in sorted(inputs()):
        f = snap / _SESSIONS_FILENAME
        if f.exists():
            keys.append((snap.name, f.stat().st_mtime))
    return keys


def _library_cache_key() -> tuple[str, float] | None:
    """mtime key for the latest snapshot's ``library.json``."""
    snaps = list(inputs())
    if not snaps:
        return None
    latest = snaps[-1]
    for child in (_LIBRARY_FILENAME, _META_FILENAME):
        f = latest / child
        if f.exists():
            return (latest.name, f.stat().st_mtime)
    return (latest.name, 0.0)


# ---------------------------------------------------------------------------
# Sessions — merged across all snapshots, deduped by playtime_id.
# ---------------------------------------------------------------------------


def _iter_session_rows(snapshot_dir: Path) -> Iterator[Res[Session]]:
    """Parse ``sessions.jsonl`` inside a single snapshot."""
    path = snapshot_dir / _SESSIONS_FILENAME
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fp:
        for lineno, raw_line in enumerate(fp, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                logger.exception(f"{path}:{lineno}: invalid JSON")
                yield PSTimetrackerParseError(
                    f"{path}:{lineno}: invalid JSON ({e})"
                )
                continue
            if not isinstance(raw, dict):
                yield PSTimetrackerParseError(
                    f"{path}:{lineno}: expected JSON object, got {type(raw).__name__}"
                )
                continue
            try:
                yield parse_session(raw)
            except Exception as e:
                logger.exception(f"{path}:{lineno}: failed to parse session")
                yield e


@mcachew(depends_on=_sessions_cache_key)
def sessions() -> Iterator[Res[Session]]:
    """Every observed session across every snapshot, deduped by playtime_id.

    Newer snapshots win: if ps-timetracker rewrites a session (e.g. the user
    edits start/end times), subsequent scrapes replace the stored version.

    Output order: chronological by ``start_local``. Rows with no
    ``start_local`` sort before timestamped rows, ordered by ``playtime_id``
    for determinism.
    """
    # Iterate newest → oldest so the first Session we see for a given
    # playtime_id is already the freshest version.
    snaps = list(reversed(inputs()))
    seen: dict[int, Session] = {}
    errors: list[Exception] = []
    for snap in snaps:
        for item in _iter_session_rows(snap):
            if isinstance(item, Exception):
                errors.append(item)
                continue
            if item.playtime_id in seen:
                continue
            seen[item.playtime_id] = item

    yield from errors
    yield from sorted(
        seen.values(),
        key=lambda s: (
            s.start_local is None,
            s.start_local or datetime.min,
            s.playtime_id,
        ),
    )


# ---------------------------------------------------------------------------
# Library — latest-snapshot only.
# ---------------------------------------------------------------------------


def _parse_meta(snapshot_dir: Path) -> tuple[datetime | None, str | None]:
    """Read ``fetched_at_utc`` and ``profile`` from ``meta.json`` if present."""
    path = snapshot_dir / _META_FILENAME
    if not path.exists():
        return None, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"{path}: unreadable ({e}); ignoring meta")
        return None, None
    if not isinstance(raw, dict):
        logger.warning(f"{path}: expected JSON object, got {type(raw).__name__}")
        return None, None

    fetched_at: datetime | None = None
    raw_fetched = raw.get("fetched_at_utc")
    if isinstance(raw_fetched, str) and raw_fetched:
        try:
            # fromisoformat accepts both "...+00:00" and trailing "Z" on 3.11+,
            # but we normalise explicitly for older runtimes the spec targets.
            fetched_at = datetime.fromisoformat(raw_fetched.replace("Z", "+00:00"))
        except ValueError as e:
            logger.warning(f"{path}: bad fetched_at_utc {raw_fetched!r} ({e})")

    profile = raw.get("profile")
    if profile is not None and not isinstance(profile, str):
        logger.warning(f"{path}: profile is {type(profile).__name__}, expected str")
        profile = None

    return fetched_at, profile


def _parse_library_file(snapshot_dir: Path) -> tuple[LibraryGame, ...]:
    """Parse ``library.json`` inside ``snapshot_dir``."""
    path = snapshot_dir / _LIBRARY_FILENAME
    if not path.exists():
        return ()
    with path.open(encoding="utf-8") as fp:
        raw = json.load(fp)
    if not isinstance(raw, list):
        raise PSTimetrackerParseError(
            f"{path}: expected a JSON array at the root, got {type(raw).__name__}"
        )
    games: list[LibraryGame] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise PSTimetrackerParseError(
                f"{path}[{idx}]: expected object, got {type(entry).__name__}"
            )
        games.append(parse_library_game(entry))
    return tuple(games)


@mcachew(depends_on=_library_cache_key)
def library() -> Library:
    """Latest-snapshot aggregate view of the profile's game library."""
    snap = _latest()
    fetched_at, profile = _parse_meta(snap)
    games = _parse_library_file(snap)
    return Library(fetched_at_utc=fetched_at, profile=profile, games=games)


# ---------------------------------------------------------------------------
# Stats for `hpi doctor`
# ---------------------------------------------------------------------------


def stats() -> Stats:
    def _library_size() -> int:
        return len(library().games)

    return {
        **stat(sessions),
        "library": _library_size(),
    }


__all__ = [
    "inputs",
    "library",
    "sessions",
    "stats",
]
