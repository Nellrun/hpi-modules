"""
Shared domain models and low-level helpers for the Trakt modules.

Defines domain types (``SiteIds``, ``Movie``, ``Show``, ``Season``,
``Episode``, ``HistoryEntry``, ``Rating``, ``WatchListEntry``, ``Like``,
``Follow``, ``Comment``, ``TraktList``) and the :func:`parse_export` entry
point that turns a raw ``traktexport export`` JSON dump into those types.

The schema mirrors the shape of the original `purarue/traktexport`_ DAL —
we reimplement it locally so that ``hpi-modules`` does not pull in the full
``traktexport`` CLI (which drags in IPython, pytrakt, click, logzero and
backoff just to parse a JSON blob). The trade-off is ~200 lines of code for
~30 MB of transitive dependencies; given how stable the schema is (it
reflects the Trakt REST API, which is versioned), that seems worth it.

.. _purarue/traktexport: https://github.com/purarue/traktexport
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Media identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SiteIds:
    """External identifiers Trakt keeps alongside every media entity.

    ``trakt_id`` is always present; the remaining fields are optional — Trakt
    only populates whatever upstream mapping is known.
    """

    trakt_id: int
    trakt_slug: str | None = None
    imdb_id: str | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    tvrage_id: int | None = None


@dataclass(frozen=True, slots=True)
class Movie:
    title: str
    year: int | None
    ids: SiteIds


@dataclass(frozen=True, slots=True)
class Show:
    title: str
    year: int | None
    ids: SiteIds


@dataclass(frozen=True, slots=True)
class Season:
    season: int
    ids: SiteIds
    show: Show


@dataclass(frozen=True, slots=True)
class Episode:
    title: str | None
    season: int
    episode: int
    ids: SiteIds
    show: Show


# Media-entry union used by several wrapping types.
MediaEntry = Movie | Show | Season | Episode


# ---------------------------------------------------------------------------
# User-activity entities
# ---------------------------------------------------------------------------


# `action` comes straight from Trakt: one of "scrobble", "checkin", "watch".
# We keep it as a plain string so new values don't break parsing.
HistoryAction = str


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """A single ``/users/me/history`` record — one watch event."""

    history_id: int
    watched_at: datetime
    action: HistoryAction
    media_type: Literal["movie", "episode"]
    media_data: Movie | Episode


@dataclass(frozen=True, slots=True)
class Rating:
    rated_at: datetime
    rating: int
    """Trakt rates on a 1..10 integer scale."""
    media_type: Literal["movie", "show", "season", "episode"]
    media_data: MediaEntry


@dataclass(frozen=True, slots=True)
class WatchListEntry:
    listed_at: datetime
    listed_at_id: int
    """Internal watchlist row id (``id`` in the Trakt response)."""
    media_type: Literal["movie", "show"]
    media_data: Movie | Show


@dataclass(frozen=True, slots=True)
class Comment:
    comment_id: int
    text: str
    created_at: datetime
    updated_at: datetime
    likes: int
    username: str


@dataclass(frozen=True, slots=True)
class TraktList:
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    likes: int
    username: str


@dataclass(frozen=True, slots=True)
class Like:
    liked_at: datetime
    media_type: Literal["list", "comment"]
    media_data: TraktList | Comment


@dataclass(frozen=True, slots=True)
class Follow:
    followed_at: datetime
    username: str


@dataclass(frozen=True, slots=True)
class FullTraktExport:
    """The full parsed dump of a single ``traktexport export`` run."""

    username: str
    followers: tuple[Follow, ...]
    following: tuple[Follow, ...]
    likes: tuple[Like, ...]
    stats: dict[str, Any]
    settings: dict[str, Any]
    watchlist: tuple[WatchListEntry, ...]
    ratings: tuple[Rating, ...]
    history: tuple[HistoryEntry, ...]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TraktParseError(ValueError):
    """Raised when a row in the export cannot be parsed."""


# ---------------------------------------------------------------------------
# Primitive parsers
# ---------------------------------------------------------------------------


def parse_trakt_datetime(value: str) -> datetime:
    """Parse a Trakt API timestamp into a timezone-aware UTC ``datetime``.

    Trakt emits ISO-8601 with a trailing ``Z`` (e.g. ``"2024-05-01T09:10:11.000Z"``).
    ``datetime.fromisoformat`` only learned to parse that suffix in 3.11; we
    support 3.10 by swapping ``Z`` for the equivalent ``+00:00`` first.
    """
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    # Trakt is always UTC; normalise naïve values just in case.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_ids(raw: dict[str, Any]) -> SiteIds:
    """Extract a :class:`SiteIds` from the ``ids`` sub-dict on every media entity."""
    if "trakt" not in raw:
        raise TraktParseError(f"ids dict is missing 'trakt': {raw!r}")
    return SiteIds(
        trakt_id=int(raw["trakt"]),
        trakt_slug=raw.get("slug"),
        imdb_id=raw.get("imdb"),
        tmdb_id=raw.get("tmdb"),
        tvdb_id=raw.get("tvdb"),
        tvrage_id=raw.get("tvrage"),
    )


def _parse_movie(raw: dict[str, Any]) -> Movie:
    return Movie(title=raw["title"], year=raw.get("year"), ids=_parse_ids(raw["ids"]))


def _parse_show(raw: dict[str, Any]) -> Show:
    return Show(title=raw["title"], year=raw.get("year"), ids=_parse_ids(raw["ids"]))


def _parse_episode(raw: dict[str, Any], show: Show) -> Episode:
    return Episode(
        title=raw.get("title"),
        season=int(raw["season"]),
        episode=int(raw["number"]),
        ids=_parse_ids(raw["ids"]),
        show=show,
    )


def _parse_season(raw: dict[str, Any], show: Show) -> Season:
    return Season(
        season=int(raw["number"]),
        ids=_parse_ids(raw["ids"]),
        show=show,
    )


def _parse_media(raw: dict[str, Any]) -> tuple[str, MediaEntry]:
    """Parse the ``type`` + corresponding media sub-dict common to most list entries.

    Returns a ``(media_type, media_data)`` tuple. Supports every media kind
    Trakt may hand back on ``history``/``ratings``/``watchlist``/``collection``:
    movie, show, season, episode.
    """
    media_type = raw.get("type")
    if media_type == "movie":
        return "movie", _parse_movie(raw["movie"])
    if media_type == "show":
        return "show", _parse_show(raw["show"])
    if media_type == "season":
        show = _parse_show(raw["show"])
        return "season", _parse_season(raw["season"], show=show)
    if media_type == "episode":
        show = _parse_show(raw["show"])
        return "episode", _parse_episode(raw["episode"], show=show)
    raise TraktParseError(f"unknown media type: {media_type!r} in {raw!r}")


# ---------------------------------------------------------------------------
# Entity parsers
# ---------------------------------------------------------------------------


def parse_history_entry(raw: dict[str, Any]) -> HistoryEntry:
    media_type, media_data = _parse_media(raw)
    if media_type not in ("movie", "episode"):
        raise TraktParseError(
            f"history entries must be movie or episode, got {media_type!r}"
        )
    return HistoryEntry(
        history_id=int(raw["id"]),
        watched_at=parse_trakt_datetime(raw["watched_at"]),
        action=raw.get("action", "watch"),
        media_type=media_type,  # type: ignore[arg-type]
        media_data=media_data,  # type: ignore[arg-type]
    )


def parse_rating(raw: dict[str, Any]) -> Rating:
    media_type, media_data = _parse_media(raw)
    return Rating(
        rated_at=parse_trakt_datetime(raw["rated_at"]),
        rating=int(raw["rating"]),
        media_type=media_type,  # type: ignore[arg-type]
        media_data=media_data,
    )


def parse_watchlist_entry(raw: dict[str, Any]) -> WatchListEntry:
    media_type, media_data = _parse_media(raw)
    if media_type not in ("movie", "show"):
        raise TraktParseError(
            f"watchlist entries must be movie or show, got {media_type!r}"
        )
    return WatchListEntry(
        listed_at=parse_trakt_datetime(raw["listed_at"]),
        listed_at_id=int(raw["id"]),
        media_type=media_type,  # type: ignore[arg-type]
        media_data=media_data,  # type: ignore[arg-type]
    )


def _parse_comment(raw: dict[str, Any]) -> Comment:
    return Comment(
        comment_id=int(raw["id"]),
        text=raw.get("comment", ""),
        created_at=parse_trakt_datetime(raw["created_at"]),
        updated_at=parse_trakt_datetime(raw.get("updated_at", raw["created_at"])),
        likes=int(raw.get("likes", 0)),
        username=raw.get("user", {}).get("username", ""),
    )


def _parse_list(raw: dict[str, Any]) -> TraktList:
    return TraktList(
        name=raw.get("name", ""),
        description=raw.get("description", "") or "",
        created_at=parse_trakt_datetime(raw["created_at"]),
        updated_at=parse_trakt_datetime(raw.get("updated_at", raw["created_at"])),
        likes=int(raw.get("likes", 0)),
        username=raw.get("user", {}).get("username", ""),
    )


def parse_like(raw: dict[str, Any]) -> Like:
    """Parse a ``/users/me/likes/*`` record (liked list or liked comment)."""
    media_type = raw.get("type")
    liked_at = parse_trakt_datetime(raw["liked_at"])
    if media_type == "list":
        return Like(
            liked_at=liked_at, media_type="list", media_data=_parse_list(raw["list"])
        )
    if media_type == "comment":
        return Like(
            liked_at=liked_at,
            media_type="comment",
            media_data=_parse_comment(raw["comment"]),
        )
    raise TraktParseError(f"unknown like type: {media_type!r} in {raw!r}")


def parse_follow(raw: dict[str, Any]) -> Follow:
    """Parse a follower/following record.

    Trakt returns the key as either ``followed_at`` (followers list) or the
    same for following; we accept both without caring which endpoint supplied
    the dict.
    """
    return Follow(
        followed_at=parse_trakt_datetime(raw["followed_at"]),
        username=raw.get("user", {}).get("username", raw.get("username", "")),
    )


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def parse_export(data: dict[str, Any]) -> FullTraktExport:
    """Parse a full ``traktexport export`` dump into typed entities.

    The function never raises on individual bad rows — it lets them through
    the parser and any exceptions surface at call-site (the higher-level HPI
    streams in :mod:`my.trakt.export` wrap them into :class:`Res` values
    instead). This keeps :func:`parse_export` simple for ad-hoc consumers.
    """
    return FullTraktExport(
        username=data.get("username", ""),
        followers=tuple(parse_follow(r) for r in data.get("followers") or ()),
        following=tuple(parse_follow(r) for r in data.get("following") or ()),
        likes=tuple(parse_like(r) for r in data.get("likes") or ()),
        stats=dict(data.get("stats") or {}),
        settings=dict(data.get("settings") or {}),
        watchlist=tuple(parse_watchlist_entry(r) for r in data.get("watchlist") or ()),
        ratings=tuple(parse_rating(r) for r in data.get("ratings") or ()),
        history=tuple(parse_history_entry(r) for r in data.get("history") or ()),
    )


__all__ = [
    "Comment",
    "Episode",
    "Follow",
    "FullTraktExport",
    "HistoryAction",
    "HistoryEntry",
    "Like",
    "MediaEntry",
    "Movie",
    "Rating",
    "Season",
    "Show",
    "SiteIds",
    "TraktList",
    "TraktParseError",
    "WatchListEntry",
    "parse_export",
    "parse_follow",
    "parse_history_entry",
    "parse_like",
    "parse_rating",
    "parse_trakt_datetime",
    "parse_watchlist_entry",
]
