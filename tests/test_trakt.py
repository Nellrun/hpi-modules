"""Tests for the ``my.trakt`` modules."""

from __future__ import annotations

import json
import shutil
import sys
import types
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_JSON = REPO_ROOT / "testdata" / "trakt-export-sample.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_config() -> Iterator[types.ModuleType]:
    """Install a clean in-memory ``my.config`` for the test.

    Same shape as tests/test_harvester.py — duplicated here so the two
    suites don't accidentally share state (pytest re-runs aside).
    """
    original = sys.modules.get("my.config")
    cfg = types.ModuleType("my.config")
    cfg.__path__ = []  # type: ignore[attr-defined]

    # Disable cachew so the module's @mcachew-decorated streams run directly.
    class core:
        cache_dir = None

    cfg.core = core  # type: ignore[attr-defined]
    sys.modules["my.config"] = cfg
    _reset_trakt_modules()
    try:
        yield cfg
    finally:
        if original is None:
            sys.modules.pop("my.config", None)
        else:
            sys.modules["my.config"] = original
        _reset_trakt_modules()


def _reset_trakt_modules() -> None:
    """Drop cached ``my.trakt*`` modules so the fresh config is picked up."""
    for name in list(sys.modules):
        if name.startswith("my.trakt"):
            del sys.modules[name]


def _install_harvester_snapshot(root: Path, timestamp: str) -> Path:
    """Place the sample JSON under a harvester-layout ``trakt/<timestamp>.json``."""
    service = root / "trakt"
    service.mkdir(parents=True, exist_ok=True)
    dst = service / f"{timestamp}.json"
    shutil.copy(SAMPLE_JSON, dst)
    return dst


def _set_harvester_root(cfg: types.ModuleType, root: Path) -> None:
    class harvester:
        pass

    harvester.root = str(root)  # type: ignore[attr-defined]
    cfg.harvester = harvester  # type: ignore[attr-defined]


def _set_trakt_section(cfg: types.ModuleType, **attrs: object) -> None:
    section = types.SimpleNamespace(**attrs)
    cfg.trakt = section  # type: ignore[attr-defined]


@pytest.fixture
def with_harvester_snapshot(
    fake_config: types.ModuleType, tmp_path: Path
) -> tuple[types.ModuleType, Path]:
    """Harvester root with one trakt snapshot → the most common configuration."""
    _set_harvester_root(fake_config, tmp_path)
    _install_harvester_snapshot(tmp_path, "2024-04-06T03-00-00")
    return fake_config, tmp_path


# ---------------------------------------------------------------------------
# Pure unit tests for my.trakt.common
# ---------------------------------------------------------------------------


class TestCommon:
    """Parsers are pure — no filesystem, no network, no config."""

    def test_parse_trakt_datetime_with_z(self) -> None:
        from my.trakt.common import parse_trakt_datetime

        got = parse_trakt_datetime("2024-04-01T22:30:00.000Z")
        assert got == datetime(2024, 4, 1, 22, 30, tzinfo=timezone.utc)

    def test_parse_trakt_datetime_without_z(self) -> None:
        from my.trakt.common import parse_trakt_datetime

        # Trakt almost always emits Z, but the parser accepts plain ISO too.
        got = parse_trakt_datetime("2024-04-01T22:30:00+00:00")
        assert got.tzinfo is not None
        assert got == datetime(2024, 4, 1, 22, 30, tzinfo=timezone.utc)

    def test_parse_export_returns_typed_tuples(self) -> None:
        from my.trakt.common import FullTraktExport, parse_export

        raw = json.loads(SAMPLE_JSON.read_text())
        parsed = parse_export(raw)
        assert isinstance(parsed, FullTraktExport)
        assert parsed.username == "nellrun"
        assert len(parsed.history) == 3
        assert len(parsed.ratings) == 2
        assert len(parsed.watchlist) == 2
        assert len(parsed.likes) == 2
        assert len(parsed.followers) == 1
        assert len(parsed.following) == 1
        assert parsed.stats["movies"]["plays"] == 42

    def test_history_entry_movie_shape(self) -> None:
        from my.trakt.common import Movie, parse_export

        raw = json.loads(SAMPLE_JSON.read_text())
        parsed = parse_export(raw)
        # First entry in the sample is a movie (Parasite).
        first = parsed.history[0]
        assert first.media_type == "movie"
        assert isinstance(first.media_data, Movie)
        assert first.media_data.title == "Parasite"
        assert first.media_data.year == 2019
        assert first.media_data.ids.imdb_id == "tt6751668"
        assert first.action == "scrobble"
        assert first.watched_at.tzinfo is not None

    def test_history_entry_episode_shape(self) -> None:
        from my.trakt.common import Episode, parse_export

        raw = json.loads(SAMPLE_JSON.read_text())
        parsed = parse_export(raw)
        # Second entry is an episode — it carries the parent Show.
        ep_entry = parsed.history[1]
        assert ep_entry.media_type == "episode"
        assert isinstance(ep_entry.media_data, Episode)
        assert ep_entry.media_data.show.title == "Breaking Bad"
        assert ep_entry.media_data.season == 1
        assert ep_entry.media_data.episode == 1
        assert ep_entry.media_data.title == "Pilot"

    def test_rating_episode_carries_show(self) -> None:
        from my.trakt.common import Episode, parse_export

        raw = json.loads(SAMPLE_JSON.read_text())
        parsed = parse_export(raw)
        episode_ratings = [r for r in parsed.ratings if r.media_type == "episode"]
        assert len(episode_ratings) == 1
        r = episode_ratings[0]
        assert r.rating == 10
        assert isinstance(r.media_data, Episode)
        assert r.media_data.show.title == "Breaking Bad"

    def test_like_kinds_parsed(self) -> None:
        from my.trakt.common import Comment, TraktList, parse_export

        raw = json.loads(SAMPLE_JSON.read_text())
        parsed = parse_export(raw)
        kinds = {like.media_type for like in parsed.likes}
        assert kinds == {"list", "comment"}
        list_like = next(lk for lk in parsed.likes if lk.media_type == "list")
        assert isinstance(list_like.media_data, TraktList)
        assert list_like.media_data.name == "Best films of 2023"
        comment_like = next(lk for lk in parsed.likes if lk.media_type == "comment")
        assert isinstance(comment_like.media_data, Comment)
        assert comment_like.media_data.text == "Great episode!"

    def test_parse_export_rejects_unknown_media_type(self) -> None:
        from my.trakt.common import TraktParseError, parse_export

        bad = {"history": [{"id": 1, "watched_at": "2024-01-01T00:00:00Z", "type": "seance"}]}
        with pytest.raises(TraktParseError):
            parse_export(bad)

    def test_empty_export_is_valid(self) -> None:
        from my.trakt.common import parse_export

        parsed = parse_export({})
        assert parsed.username == ""
        assert parsed.history == ()
        assert parsed.stats == {}


# ---------------------------------------------------------------------------
# Integration with my.harvester.snapshot
# ---------------------------------------------------------------------------


class TestExportViaHarvester:
    """Driving :mod:`my.trakt.export` through a fake harvester layout."""

    def test_inputs_lists_snapshots(
        self, with_harvester_snapshot: tuple[types.ModuleType, Path]
    ) -> None:
        _, root = with_harvester_snapshot
        from my.trakt import export

        inputs = list(export.inputs())
        assert len(inputs) == 1
        assert inputs[0].name == "2024-04-06T03-00-00.json"
        assert inputs[0].parent == root / "trakt"

    def test_history_yields_typed_entries(
        self, with_harvester_snapshot: tuple[types.ModuleType, Path]
    ) -> None:
        from my.trakt import export
        from my.trakt.common import HistoryEntry

        entries = list(export.history())
        assert all(isinstance(e, HistoryEntry) for e in entries)
        assert len(entries) == 3

    def test_ratings_and_watchlist(
        self, with_harvester_snapshot: tuple[types.ModuleType, Path]
    ) -> None:
        from my.trakt import export

        ratings = list(export.ratings())
        assert len(ratings) == 2
        watchlist = list(export.watchlist())
        assert [w.media_data.title for w in watchlist] == ["Dune: Part Two", "Shogun"]

    def test_profile_stats_is_passthrough_dict(
        self, with_harvester_snapshot: tuple[types.ModuleType, Path]
    ) -> None:
        from my.trakt import export

        stats_dict = export.profile_stats()
        assert stats_dict["movies"]["plays"] == 42

    def test_picks_latest_when_multiple_snapshots(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _install_harvester_snapshot(tmp_path, "2024-04-01T03-00-00")
        newest = _install_harvester_snapshot(tmp_path, "2024-04-06T03-00-00")
        # Mutate the older file so a bug that picks it would be visible —
        # parsing a broken dict would raise, failing the test.
        older = tmp_path / "trakt" / "2024-04-01T03-00-00.json"
        older.write_text("{}")

        from my.trakt import export

        assert list(export.inputs())[-1] == newest
        # parse succeeds → the newest snapshot was used.
        assert len(list(export.history())) == 3

    def test_empty_list_yields_nothing(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        """Empty arrays in the dump must not surface as parse errors.

        Regression for a bug where ``rows = raw.get(key) or ()`` turned an
        empty ``[]`` into a tuple, then failed the ``isinstance(list)`` check
        and yielded a spurious ``TraktParseError``.
        """
        _set_harvester_root(fake_config, tmp_path)
        service = tmp_path / "trakt"
        service.mkdir(parents=True)
        (service / "2024-04-06T03-00-00.json").write_text(
            json.dumps({"likes": [], "followers": [], "following": []})
        )

        from my.trakt import export

        assert list(export.likes()) == []
        assert list(export.followers()) == []
        assert list(export.following()) == []

    def test_missing_key_yields_nothing(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        """A snapshot that simply lacks a key should not error either."""
        _set_harvester_root(fake_config, tmp_path)
        service = tmp_path / "trakt"
        service.mkdir(parents=True)
        (service / "2024-04-06T03-00-00.json").write_text("{}")

        from my.trakt import export

        assert list(export.history()) == []
        assert list(export.likes()) == []
        assert list(export.followers()) == []

    def test_bad_rows_yielded_as_exceptions(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        """HPI convention: one broken entry doesn't break the stream."""
        _set_harvester_root(fake_config, tmp_path)
        service = tmp_path / "trakt"
        service.mkdir(parents=True)
        (service / "2024-04-06T03-00-00.json").write_text(
            json.dumps(
                {
                    "history": [
                        # valid
                        {
                            "id": 1,
                            "watched_at": "2024-04-01T22:30:00.000Z",
                            "type": "movie",
                            "action": "watch",
                            "movie": {
                                "title": "Good",
                                "year": 2020,
                                "ids": {"trakt": 1, "slug": "good"},
                            },
                        },
                        # invalid — missing required ids.trakt
                        {
                            "id": 2,
                            "watched_at": "2024-04-02T22:30:00.000Z",
                            "type": "movie",
                            "movie": {"title": "Bad", "year": 2020, "ids": {}},
                        },
                    ]
                }
            )
        )

        from my.trakt import export

        entries = list(export.history())
        assert len(entries) == 2
        types_ = [type(e).__name__ for e in entries]
        assert types_[0] == "HistoryEntry"
        assert isinstance(entries[1], Exception)


# ---------------------------------------------------------------------------
# Karlicoss-compatible fallback (no harvester root)
# ---------------------------------------------------------------------------


class TestKarlicossFallback:
    """When there's no harvester root, the export_path config still works."""

    def test_export_path_glob(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        # The karlicoss get_files path doesn't need harvester-style timestamps
        # in filenames — any match for the glob is fine.
        dst = legacy / "trakt-2024-04-06.json"
        shutil.copy(SAMPLE_JSON, dst)
        _set_trakt_section(fake_config, export_path=str(legacy / "*.json"))

        from my.trakt import export

        assert list(export.inputs()) == [dst]
        assert len(list(export.history())) == 3


# ---------------------------------------------------------------------------
# Facade (my.trakt.all) proxies to export
# ---------------------------------------------------------------------------


class TestAllFacade:
    def test_all_proxies_history(
        self, with_harvester_snapshot: tuple[types.ModuleType, Path]
    ) -> None:
        from my.trakt import all as trakt_all
        from my.trakt.common import HistoryEntry

        entries = list(trakt_all.history())
        assert len(entries) == 3
        assert all(isinstance(e, HistoryEntry) for e in entries)

    def test_all_proxies_profile_stats(
        self, with_harvester_snapshot: tuple[types.ModuleType, Path]
    ) -> None:
        from my.trakt import all as trakt_all

        assert trakt_all.profile_stats()["movies"]["plays"] == 42
