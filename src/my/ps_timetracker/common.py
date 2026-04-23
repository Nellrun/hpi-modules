"""
Shared domain models and JSON-row parsers for the ps-timetracker modules.

The harvester-side scraper (``ps-timetracker-export``) emits two JSON shapes
per snapshot:

* ``sessions.jsonl`` — one object per line, schema::

      {
        "playtime_id":      int,       # stable row id; primary key for dedup
        "game_id":          str|null,  # PSN content id, e.g. "PPSA02530_00"
        "game_title":       str|null,
        "platform":         str|null,  # "PS5" | "PS4" | "PS3" | "PSVITA"
        "duration_seconds": int|null,
        "duration_text":    str|null,  # human-readable original, e.g. "1:48 hours"
        "start_local":      str|null,  # "YYYY-MM-DD HH:MM" in account-local tz
        "end_local":        str|null,
      }

* ``library.json`` — JSON array of per-game aggregates from the profile
  landing page. ``hours_sort`` / ``avg_session_sort`` are raw ``data-sort``
  attributes from the scraped HTML; they come through as opaque ints so the
  consumer can decide how to interpret them.

Timestamps on ps-timetracker.com are rendered in the account's local
timezone, not UTC. We parse them into *naive* ``datetime`` objects and leave
timezone localization to downstream consumers that know the account's tz.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Matches the "YYYY-MM-DD HH:MM" format ps-timetracker renders in every
# timestamp column (sessions start/end, library last-played).
_LOCAL_DATETIME_FORMAT = "%Y-%m-%d %H:%M"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PSTimetrackerParseError(ValueError):
    """Raised when a row in a harvester snapshot cannot be parsed."""


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Session:
    """One gaming session as observed by the ps-timetracker friend-bot."""

    playtime_id: int
    game_id: str | None
    game_title: str | None
    platform: str | None
    duration: timedelta | None
    """Wall-clock duration. May be shorter than ``end_local - start_local`` if
    the bot missed presence pings in the middle of the session, so keep it as
    a separate field rather than deriving from the timestamps."""
    start_local: datetime | None
    """Naive — account-local timezone. See module docstring."""
    end_local: datetime | None


@dataclass(frozen=True, slots=True)
class LibraryGame:
    """Aggregate stats for one game as shown on the profile landing page."""

    rank: int | None
    game_id: str | None
    title: str | None
    platform: str | None
    total_duration: timedelta | None
    total_duration_text: str | None
    """Unparsed original (e.g. ``"32:05 hours"``). Kept so downstream can
    distinguish "32 hours" vs "32:05" without re-parsing."""
    sessions_count: int | None
    avg_session: timedelta | None
    avg_session_text: str | None
    last_played_local: datetime | None
    """Naive — account-local timezone. See module docstring."""


@dataclass(frozen=True, slots=True)
class Library:
    """Snapshot of the full game library at one point in time."""

    fetched_at_utc: datetime | None
    """UTC timestamp from the snapshot's ``meta.json`` (not the snapshot
    directory name, because the directory is promoted atomically after the
    scrape finishes — use whichever the consumer trusts more)."""
    profile: str | None
    games: tuple[LibraryGame, ...]


# ---------------------------------------------------------------------------
# Primitive parsers
# ---------------------------------------------------------------------------


def _parse_local_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return datetime.strptime(stripped, _LOCAL_DATETIME_FORMAT)
    except ValueError as e:
        raise PSTimetrackerParseError(
            f"expected naive local datetime 'YYYY-MM-DD HH:MM', got {value!r}"
        ) from e


def _parse_seconds(value: Any) -> timedelta | None:
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is a subclass of int — reject explicitly so malformed data
        # doesn't silently pass through as a zero-ish timedelta.
        raise PSTimetrackerParseError(f"expected int seconds, got bool {value!r}")
    if isinstance(value, int):
        return timedelta(seconds=value)
    raise PSTimetrackerParseError(f"expected int seconds or null, got {type(value).__name__}")


# ---------------------------------------------------------------------------
# Row parsers
# ---------------------------------------------------------------------------


def parse_session(raw: dict[str, Any]) -> Session:
    if "playtime_id" not in raw:
        raise PSTimetrackerParseError(f"session row missing 'playtime_id': {raw!r}")
    return Session(
        playtime_id=int(raw["playtime_id"]),
        game_id=raw.get("game_id"),
        game_title=raw.get("game_title"),
        platform=raw.get("platform"),
        duration=_parse_seconds(raw.get("duration_seconds")),
        start_local=_parse_local_datetime(raw.get("start_local")),
        end_local=_parse_local_datetime(raw.get("end_local")),
    )


def parse_library_game(raw: dict[str, Any]) -> LibraryGame:
    # last_played_local can arrive in shapes the scraper doesn't normalise
    # (ps-timetracker renders it as relative time / bare HH:MM for very
    # recent plays). Those rows are not parse errors — the aggregate is
    # best-effort, so we log and drop the timestamp rather than failing the
    # whole library view. Durations are similarly opaque, so they stay
    # strict: a malformed ``hours_sort`` almost certainly indicates a bug.
    last_played_raw = raw.get("last_played_local")
    try:
        last_played = _parse_local_datetime(last_played_raw)
    except PSTimetrackerParseError as e:
        logger.warning(
            "library row: unparseable last_played_local %r (%s); leaving unset",
            last_played_raw,
            e,
        )
        last_played = None
    return LibraryGame(
        rank=raw.get("rank"),
        game_id=raw.get("game_id"),
        title=raw.get("game_title"),
        platform=raw.get("platform"),
        total_duration=_parse_seconds(raw.get("hours_sort")),
        total_duration_text=raw.get("hours_text"),
        sessions_count=raw.get("sessions_count"),
        avg_session=_parse_seconds(raw.get("avg_session_sort")),
        avg_session_text=raw.get("avg_session_text"),
        last_played_local=last_played,
    )


__all__ = [
    "Library",
    "LibraryGame",
    "PSTimetrackerParseError",
    "Session",
    "parse_library_game",
    "parse_session",
]
