"""
Parser for ``gwm-stats-export`` snapshot files.

Each run of the harvester ``gwm_stats`` exporter writes one JSON file
(``<harvester_root>/gwm_stats/<timestamp>.json``) containing the full
``/api/player`` response.

* :func:`sessions` merges ``sessionsLog`` across every snapshot, deduped
  by ``(title_id, started_at, source)``. The aggregator may rewrite a
  session (e.g. when it learns the real end timestamp after a poll),
  so newer snapshots win.
* :func:`trophies` does the same for ``trophies[]``, deduped by
  ``(source, np_comm_id, trophy_id)``.
* :func:`summary` returns the latest-snapshot view of the aggregate
  fields (``totals``, ``topGames``, ``platformBreakdown``).

Expected configuration (``~/.config/my/my/config/__init__.py``). Pick one:

.. code-block:: python

    # 1. Harvester-powered (recommended):
    class harvester:
        root = '/path/to/hpi-harvester/data'

    # 2. Classic karlicoss/HPI shape — point at a directory that contains
    #    timestamped snapshot files in the harvester layout:
    class gwm_stats:
        export_path = '~/data/gwm_stats'

    # 3. Rename the exporter in the harvester YAML? Override the source name:
    class gwm_stats:
        harvester_name = 'gwm_stats_mine'

Self-check::

    hpi doctor my.gwm_stats.export
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from my.core import Res, Stats, make_logger, stat
from my.harvester import snapshot

from .common import (
    GwmStatsParseError,
    PlatformStats,
    Session,
    Summary,
    TopGame,
    Trophy,
    parse_platform_stats,
    parse_session,
    parse_top_game,
    parse_totals,
    parse_trophy,
)

logger = make_logger(__name__)


_DEFAULT_SOURCE = "gwm_stats"
_SNAPSHOT_EXTENSIONS = (".json",)


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------


def inputs() -> Sequence[Path]:
    """Every gwm-stats snapshot file known to the harvester.

    Sorted ascending (oldest → newest). Empty when no snapshot has been
    produced yet — downstream callers raise :class:`FileNotFoundError` with
    an actionable message via :func:`my.harvester.snapshot`.
    """
    snap = snapshot(
        source=_DEFAULT_SOURCE,
        module="gwm_stats",
        extensions=_SNAPSHOT_EXTENSIONS,
    )
    return snap.all()


def _latest() -> Path:
    """The freshest snapshot file on disk."""
    snap = snapshot(
        source=_DEFAULT_SOURCE,
        module="gwm_stats",
        extensions=_SNAPSHOT_EXTENSIONS,
    )
    latest = snap.latest()
    logger.info(f"using latest gwm-stats snapshot: {latest}")
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


def _cache_key() -> list[tuple[str, float]]:
    """mtime key over every snapshot we might merge."""
    return [(p.name, p.stat().st_mtime) for p in inputs()]


def _latest_cache_key() -> tuple[str, float] | None:
    snaps = list(inputs())
    if not snaps:
        return None
    return (snaps[-1].name, snaps[-1].stat().st_mtime)


# ---------------------------------------------------------------------------
# Snapshot reader
# ---------------------------------------------------------------------------


def _read_snapshot(path: Path) -> dict[str, Any] | Exception:
    """Read one snapshot file, returning an exception on failure rather than
    raising — we don't want a single corrupt run to wipe the whole feed."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.exception(f"{path}: failed to read snapshot")
        return GwmStatsParseError(f"{path}: {e}")
    if not isinstance(raw, dict):
        return GwmStatsParseError(
            f"{path}: expected JSON object at the root, got {type(raw).__name__}"
        )
    return raw


def _fetched_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@mcachew(depends_on=_cache_key)
def sessions() -> Iterator[Res[Session]]:
    """Every session across every snapshot, deduped by
    ``(title_id, started_at, source)``.

    Newer snapshots win: subsequent scrapes replace the stored version of
    a session. Output order: chronological by ``started_at``.
    """
    # Iterate newest → oldest so the first row we accept for a given key is
    # already the freshest version.
    snaps = list(reversed(list(inputs())))
    seen: dict[tuple[str, datetime, str], Session] = {}
    errors: list[Exception] = []

    for snap_path in snaps:
        raw = _read_snapshot(snap_path)
        if isinstance(raw, Exception):
            errors.append(raw)
            continue
        rows = raw.get("sessionsLog") or []
        if not isinstance(rows, list):
            errors.append(
                GwmStatsParseError(
                    f"{snap_path}: 'sessionsLog' must be a list, "
                    f"got {type(rows).__name__}"
                )
            )
            continue
        for idx, entry in enumerate(rows):
            if not isinstance(entry, dict):
                errors.append(
                    GwmStatsParseError(
                        f"{snap_path}: sessionsLog[{idx}] is "
                        f"{type(entry).__name__}, expected object"
                    )
                )
                continue
            try:
                session = parse_session(entry)
            except Exception as e:  # noqa: BLE001 — surface every parse failure
                logger.exception(f"{snap_path}: sessionsLog[{idx}] failed to parse")
                errors.append(e)
                continue
            key = (session.title_id, session.started_at, session.source)
            seen.setdefault(key, session)

    yield from errors
    yield from sorted(seen.values(), key=lambda s: (s.started_at, s.title_id))


# ---------------------------------------------------------------------------
# Trophies
# ---------------------------------------------------------------------------


@mcachew(depends_on=_cache_key)
def trophies() -> Iterator[Res[Trophy]]:
    """Every trophy across every snapshot, deduped by
    ``(source, np_comm_id, trophy_id)``.

    Output order: by ``earned_at`` ascending; trophies with no
    ``earned_at`` sort last for determinism.
    """
    snaps = list(reversed(list(inputs())))
    seen: dict[tuple[str, str | None, int | None], Trophy] = {}
    errors: list[Exception] = []

    for snap_path in snaps:
        raw = _read_snapshot(snap_path)
        if isinstance(raw, Exception):
            errors.append(raw)
            continue
        rows = raw.get("trophies") or []
        if not isinstance(rows, list):
            errors.append(
                GwmStatsParseError(
                    f"{snap_path}: 'trophies' must be a list, got {type(rows).__name__}"
                )
            )
            continue
        for idx, entry in enumerate(rows):
            if not isinstance(entry, dict):
                errors.append(
                    GwmStatsParseError(
                        f"{snap_path}: trophies[{idx}] is "
                        f"{type(entry).__name__}, expected object"
                    )
                )
                continue
            try:
                trophy = parse_trophy(entry)
            except Exception as e:  # noqa: BLE001
                logger.exception(f"{snap_path}: trophies[{idx}] failed to parse")
                errors.append(e)
                continue
            key = (trophy.source, trophy.np_comm_id, trophy.trophy_id)
            seen.setdefault(key, trophy)

    yield from errors
    yield from sorted(
        seen.values(),
        key=lambda t: (
            t.earned_at is None,
            t.earned_at or datetime.min.replace(tzinfo=timezone.utc),
            t.source,
            t.trophy_id or 0,
        ),
    )


# ---------------------------------------------------------------------------
# Summary (latest snapshot only)
# ---------------------------------------------------------------------------


def _parse_list_field(
    raw: dict[str, Any],
    key: str,
    parser: Any,
    snap_path: Path,
) -> tuple[Any, ...]:
    rows = raw.get(key) or []
    if not isinstance(rows, list):
        logger.warning(
            f"{snap_path}: '{key}' must be a list, got {type(rows).__name__}; "
            f"treating as empty"
        )
        return ()
    out = []
    for idx, entry in enumerate(rows):
        if not isinstance(entry, dict):
            logger.warning(f"{snap_path}: {key}[{idx}] is {type(entry).__name__}; skipped")
            continue
        try:
            out.append(parser(entry))
        except GwmStatsParseError as e:
            logger.warning(f"{snap_path}: {key}[{idx}] parse error: {e}; skipped")
    return tuple(out)


@mcachew(depends_on=_latest_cache_key)
def summary() -> Summary:
    """Latest-snapshot view of the aggregate stats.

    Raises :class:`FileNotFoundError` if no snapshot exists yet — same
    contract as :func:`my.ps_timetracker.export.library`.
    """
    path = _latest()
    raw = _read_snapshot(path)
    if isinstance(raw, Exception):
        raise raw

    top_games: tuple[TopGame, ...] = _parse_list_field(raw, "topGames", parse_top_game, path)
    platforms: tuple[PlatformStats, ...] = _parse_list_field(
        raw, "platformBreakdown", parse_platform_stats, path
    )

    return Summary(
        fetched_at_utc=_fetched_at(path),
        name=raw.get("name") if isinstance(raw.get("name"), str) else None,
        player_name=raw.get("playerName")
        if isinstance(raw.get("playerName"), str)
        else None,
        member_count=raw.get("memberCount")
        if isinstance(raw.get("memberCount"), int)
        and not isinstance(raw.get("memberCount"), bool)
        else None,
        is_self=raw.get("isSelf") if isinstance(raw.get("isSelf"), bool) else None,
        totals=parse_totals(raw.get("totals") if isinstance(raw.get("totals"), dict) else None),
        top_games=top_games,
        platform_breakdown=platforms,
    )


# ---------------------------------------------------------------------------
# Stats for `hpi doctor`
# ---------------------------------------------------------------------------


def stats() -> Stats:
    def _summary_size() -> dict[str, int]:
        try:
            s = summary()
        except FileNotFoundError:
            return {"top_games": 0, "platforms": 0}
        return {"top_games": len(s.top_games), "platforms": len(s.platform_breakdown)}

    return {
        **stat(sessions),
        **stat(trophies),
        "summary": _summary_size(),
    }


__all__ = [
    "inputs",
    "sessions",
    "stats",
    "summary",
    "trophies",
]
