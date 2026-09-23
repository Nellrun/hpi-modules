"""
Shared domain models and JSON parsers for ``my.gwm_stats``.

Each ``gwm-stats-export`` run writes one JSON file. Since the site
(gowithme.club) split its monolithic ``/api/player`` into per-tab
endpoints, the exporter bundles them into one envelope::

    {
      "fetched_at": str,          # ISO-8601, stamped by the exporter
      "name": str,
      "aliases": [str, ...],
      "profile":  { ... /api/player — totals, topGames, platformBreakdown,
                    gameTotal, trophyTotal, platinumTotal, ...;
                    its sessionsLog/trophies are truncated to one page },
      "activity": { ... /api/player/activity — full "sessionsLog" },
      "games":    [ ... /api/player-games — full game library ],
      "trophies": [ ... /api/player-trophies — full trophy log ]
                  # absent when the exporter ran with --no-trophies
    }

Legacy snapshots (before the split) are the bare ``/api/player`` response,
i.e. what is now ``profile``, with complete ``sessionsLog`` and ``trophies``.

All timestamp fields are ISO-8601 UTC strings (``"...Z"``). The aggregator
itself does not promise unique session ids, so the natural key for
deduplication is ``(title_id, started_at, source)``. Trophies are keyed by
``(np_comm_id, trophy_id, source)``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GwmStatsParseError(ValueError):
    """Raised when a row in a gwm-stats snapshot cannot be parsed."""


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Session:
    """One gaming session observed by the gwm-stats aggregator."""

    title_id: str
    title_name: str | None
    platform: str | None
    source: str
    """Upstream backend: ``"psn"`` | ``"steam"`` | ``"nintendo"`` | ..."""
    started_at: datetime
    """Aware UTC."""
    ended_at: datetime | None
    duration: timedelta | None
    """``observed_seconds`` from the API — wall-clock observed play time. May
    be shorter than ``ended_at - started_at`` when the aggregator missed
    polls in the middle of the session."""


@dataclass(frozen=True, slots=True)
class Trophy:
    """One trophy/achievement earned by the player."""

    source: str
    title_name: str | None
    trophy_id: int | None
    trophy_name: str | None
    trophy_detail: str | None
    trophy_type: str | None
    """PSN values: ``"bronze"`` | ``"silver"`` | ``"gold"`` | ``"platinum"``."""
    trophy_hidden: bool | None
    rarity: float | None
    icon_url: str | None
    earned_at: datetime | None
    account_id: str | None
    online_id: str | None
    np_comm_id: str | None
    """PSN per-title trophy group id; ``None`` on non-PSN sources."""
    display_name: str | None


@dataclass(frozen=True, slots=True)
class TopGame:
    """Per-game aggregate from ``topGames[]``."""

    title_id: str | None
    title_name: str | None
    platform: str | None
    source: str | None
    total_duration: timedelta | None
    sessions_count: int | None


@dataclass(frozen=True, slots=True)
class PlatformStats:
    """Per-platform aggregate from ``platformBreakdown[]``."""

    source: str | None
    total_duration: timedelta | None
    sessions_count: int | None
    games_count: int | None


@dataclass(frozen=True, slots=True)
class GamePlatformTime:
    """Per-source play time of one game from ``games[].platforms[]``."""

    source: str | None
    total_duration: timedelta | None


@dataclass(frozen=True, slots=True)
class Game:
    """One entry of the player's game library (``/api/player-games``).

    Unlike :class:`TopGame`, this covers every game ever played, including
    lifetime play time imported from the platforms (Steam, PSN, ...) for
    titles that predate the aggregator's own session tracking.
    """

    title_id: str
    title_name: str | None
    source: str | None
    """Primary source of the ``title_id``."""
    sources: tuple[str, ...]
    """Every source the game was seen on."""
    total_duration: timedelta | None
    """Lifetime play time across every source."""
    observed_duration: timedelta | None
    """Play time observed by the aggregator's own session tracking."""
    sessions_count: int | None
    play_count: int | None
    last_played_at: datetime | None
    igdb_game_id: int | None
    cover_url: str | None
    platforms: tuple[GamePlatformTime, ...]


@dataclass(frozen=True, slots=True)
class Totals:
    """Top-level aggregate counters."""

    total_duration: timedelta | None
    sessions_count: int | None
    games_count: int | None
    avg_session: timedelta | None
    longest_session: timedelta | None
    first_started_at: datetime | None
    last_ended_at: datetime | None
    active_days: int | None = None
    """Missing from legacy snapshots."""


@dataclass(frozen=True, slots=True)
class Summary:
    """Latest-snapshot view of the player's aggregate stats."""

    fetched_at_utc: datetime | None
    """``fetched_at`` stamped by the exporter; file mtime for legacy snapshots."""
    name: str | None
    player_name: str | None
    member_count: int | None
    is_self: bool | None
    totals: Totals
    top_games: tuple[TopGame, ...]
    platform_breakdown: tuple[PlatformStats, ...]
    game_total: int | None = None
    trophy_total: int | None = None
    platinum_total: int | None = None


# ---------------------------------------------------------------------------
# Primitive parsers
# ---------------------------------------------------------------------------


def _parse_utc_datetime(value: Any) -> datetime | None:
    """Parse ``"2026-06-21T21:32:06.831Z"`` shaped strings as aware UTC."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise GwmStatsParseError(f"expected ISO datetime string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
    except ValueError as e:
        raise GwmStatsParseError(f"bad ISO datetime {value!r}: {e}") from e
    if parsed.tzinfo is None:
        # The aggregator emits explicit "Z" — naive timestamps shouldn't happen,
        # but if they do treat them as UTC rather than crashing the whole feed.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_seconds(value: Any) -> timedelta | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise GwmStatsParseError(f"expected numeric seconds, got bool {value!r}")
    if isinstance(value, (int, float)):
        return timedelta(seconds=float(value))
    raise GwmStatsParseError(f"expected numeric seconds or null, got {type(value).__name__}")


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GwmStatsParseError(f"expected str or null, got {type(value).__name__}")
    return value


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is a subclass of int — reject it so a stray "true" doesn't become 1.
        raise GwmStatsParseError(f"expected int or null, got bool {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise GwmStatsParseError(f"expected int or null, got {type(value).__name__}")


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise GwmStatsParseError(f"expected float or null, got bool {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    raise GwmStatsParseError(f"expected number or null, got {type(value).__name__}")


def _opt_bool_from_int(value: Any) -> bool | None:
    """The API returns 0/1 for ``is_self``/``trophy_hidden`` rather than bool."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    raise GwmStatsParseError(f"expected 0/1/bool/null, got {type(value).__name__}")


# ---------------------------------------------------------------------------
# Row parsers
# ---------------------------------------------------------------------------


def parse_session(raw: dict[str, Any]) -> Session:
    for required in ("title_id", "started_at", "source"):
        if raw.get(required) in (None, ""):
            raise GwmStatsParseError(f"session row missing {required!r}: {raw!r}")
    started = _parse_utc_datetime(raw["started_at"])
    assert started is not None  # checked above
    return Session(
        title_id=str(raw["title_id"]),
        title_name=_opt_str(raw.get("title_name")),
        platform=_opt_str(raw.get("platform")),
        source=str(raw["source"]),
        started_at=started,
        ended_at=_parse_utc_datetime(raw.get("ended_at")),
        duration=_parse_seconds(raw.get("observed_seconds")),
    )


def parse_trophy(raw: dict[str, Any]) -> Trophy:
    if not raw.get("source"):
        raise GwmStatsParseError(f"trophy row missing 'source': {raw!r}")
    return Trophy(
        source=str(raw["source"]),
        title_name=_opt_str(raw.get("title_name")),
        trophy_id=_opt_int(raw.get("trophy_id")),
        trophy_name=_opt_str(raw.get("trophy_name")),
        trophy_detail=_opt_str(raw.get("trophy_detail")),
        trophy_type=_opt_str(raw.get("trophy_type")),
        trophy_hidden=_opt_bool_from_int(raw.get("trophy_hidden")),
        rarity=_opt_float(raw.get("rarity")),
        icon_url=_opt_str(raw.get("icon_url")),
        earned_at=_parse_utc_datetime(raw.get("earned_at")),
        account_id=_opt_str(raw.get("account_id")),
        online_id=_opt_str(raw.get("online_id")),
        np_comm_id=_opt_str(raw.get("np_comm_id")),
        display_name=_opt_str(raw.get("display_name")),
    )


def parse_top_game(raw: dict[str, Any]) -> TopGame:
    return TopGame(
        title_id=_opt_str(raw.get("title_id")),
        title_name=_opt_str(raw.get("title_name")),
        platform=_opt_str(raw.get("platform")),
        source=_opt_str(raw.get("source")),
        total_duration=_parse_seconds(raw.get("total_seconds")),
        sessions_count=_opt_int(raw.get("sessions")),
    )


def parse_platform_stats(raw: dict[str, Any]) -> PlatformStats:
    return PlatformStats(
        source=_opt_str(raw.get("source")),
        total_duration=_parse_seconds(raw.get("total_seconds")),
        sessions_count=_opt_int(raw.get("sessions")),
        games_count=_opt_int(raw.get("games")),
    )


def parse_game(raw: dict[str, Any]) -> Game:
    if raw.get("title_id") in (None, ""):
        raise GwmStatsParseError(f"game row missing 'title_id': {raw!r}")
    sources = raw.get("sources") or []
    if not isinstance(sources, list) or not all(isinstance(x, str) for x in sources):
        raise GwmStatsParseError(f"expected list of str for 'sources', got {sources!r}")
    platforms = raw.get("platforms") or []
    if not isinstance(platforms, list):
        raise GwmStatsParseError(f"expected list for 'platforms', got {type(platforms).__name__}")
    return Game(
        title_id=str(raw["title_id"]),
        title_name=_opt_str(raw.get("title_name")),
        source=_opt_str(raw.get("source")),
        sources=tuple(sources),
        total_duration=_parse_seconds(raw.get("total_seconds")),
        observed_duration=_parse_seconds(raw.get("observed_seconds")),
        sessions_count=_opt_int(raw.get("sessions")),
        play_count=_opt_int(raw.get("play_count")),
        last_played_at=_parse_utc_datetime(raw.get("lastPlayedAt")),
        igdb_game_id=_opt_int(raw.get("igdb_game_id")),
        cover_url=_opt_str(raw.get("coverUrl")),
        platforms=tuple(
            GamePlatformTime(
                source=_opt_str(p.get("source")),
                total_duration=_parse_seconds(p.get("total_seconds")),
            )
            for p in platforms
            if isinstance(p, dict)
        ),
    )


def parse_totals(raw: dict[str, Any] | None) -> Totals:
    if not raw:
        return Totals(None, None, None, None, None, None, None)
    return Totals(
        total_duration=_parse_seconds(raw.get("total_seconds")),
        sessions_count=_opt_int(raw.get("sessions")),
        games_count=_opt_int(raw.get("games")),
        avg_session=_parse_seconds(raw.get("avg_session_seconds")),
        longest_session=_parse_seconds(raw.get("longest_session_seconds")),
        first_started_at=_parse_utc_datetime(raw.get("first_started_at")),
        last_ended_at=_parse_utc_datetime(raw.get("last_ended_at")),
        active_days=_opt_int(raw.get("active_days")),
    )


__all__ = [
    "Game",
    "GamePlatformTime",
    "GwmStatsParseError",
    "PlatformStats",
    "Session",
    "Summary",
    "TopGame",
    "Totals",
    "Trophy",
    "parse_game",
    "parse_platform_stats",
    "parse_session",
    "parse_top_game",
    "parse_totals",
    "parse_trophy",
]
