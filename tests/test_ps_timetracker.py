"""Tests for the ``my.ps_timetracker`` modules."""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_config() -> Iterator[types.ModuleType]:
    """Install a clean in-memory ``my.config`` for the test."""
    original = sys.modules.get("my.config")
    cfg = types.ModuleType("my.config")
    cfg.__path__ = []  # type: ignore[attr-defined]

    class core:
        cache_dir = None

    cfg.core = core  # type: ignore[attr-defined]
    sys.modules["my.config"] = cfg
    _reset_pst_modules()
    try:
        yield cfg
    finally:
        if original is None:
            sys.modules.pop("my.config", None)
        else:
            sys.modules["my.config"] = original
        _reset_pst_modules()


def _reset_pst_modules() -> None:
    for name in list(sys.modules):
        if name.startswith("my.ps_timetracker"):
            del sys.modules[name]


def _set_harvester_root(cfg: types.ModuleType, root: Path) -> None:
    class harvester:
        pass

    harvester.root = str(root)  # type: ignore[attr-defined]
    cfg.harvester = harvester  # type: ignore[attr-defined]


def _write_snapshot(
    root: Path,
    timestamp: str,
    *,
    sessions: list[dict] | None = None,
    library: list[dict] | None = None,
    meta: dict | None = None,
) -> Path:
    """Write a ps-timetracker snapshot under ``<root>/ps_timetracker/<ts>/``."""
    snap = root / "ps_timetracker" / timestamp
    snap.mkdir(parents=True, exist_ok=True)
    if sessions is not None:
        lines = [json.dumps(s) for s in sessions]
        (snap / "sessions.jsonl").write_text("\n".join(lines) + "\n")
    if library is not None:
        (snap / "library.json").write_text(json.dumps(library))
    if meta is not None:
        (snap / "meta.json").write_text(json.dumps(meta))
    return snap


def _sample_session(
    *,
    playtime_id: int,
    game_id: str = "PPSA02530_00",
    game_title: str = "Elden Ring",
    platform: str = "PS5",
    duration_seconds: int | None = 3600,
    start_local: str | None = "2024-04-06 20:00",
    end_local: str | None = "2024-04-06 21:00",
) -> dict:
    return {
        "playtime_id": playtime_id,
        "game_id": game_id,
        "game_title": game_title,
        "platform": platform,
        "duration_seconds": duration_seconds,
        "duration_text": None,
        "start_local": start_local,
        "end_local": end_local,
    }


def _sample_library_game(**overrides: object) -> dict:
    base: dict = {
        "rank": 1,
        "game_id": "PPSA02530_00",
        "game_title": "Elden Ring",
        "platform": "PS5",
        "hours_sort": 115500,
        "hours_text": "32:05 hours",
        "sessions_count": 48,
        "avg_session_sort": 2406,
        "avg_session_text": "40 min",
        "last_played_local": "2024-04-06 21:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# common.py — pure parsers
# ---------------------------------------------------------------------------


class TestCommon:
    def test_parse_session_minimal(self) -> None:
        from my.ps_timetracker.common import Session, parse_session

        s = parse_session({"playtime_id": 42})
        assert isinstance(s, Session)
        assert s.playtime_id == 42
        assert s.game_id is None
        assert s.duration is None
        assert s.start_local is None

    def test_parse_session_full(self) -> None:
        from my.ps_timetracker.common import parse_session

        s = parse_session(_sample_session(playtime_id=7))
        assert s.playtime_id == 7
        assert s.game_id == "PPSA02530_00"
        assert s.platform == "PS5"
        assert s.duration == timedelta(seconds=3600)
        assert s.start_local == datetime(2024, 4, 6, 20, 0)
        assert s.end_local == datetime(2024, 4, 6, 21, 0)
        # naive — no tzinfo
        assert s.start_local is not None and s.start_local.tzinfo is None

    def test_parse_session_missing_playtime_id_raises(self) -> None:
        from my.ps_timetracker.common import PSTimetrackerParseError, parse_session

        with pytest.raises(PSTimetrackerParseError):
            parse_session({"game_title": "orphan"})

    def test_parse_session_bad_datetime_raises(self) -> None:
        from my.ps_timetracker.common import PSTimetrackerParseError, parse_session

        with pytest.raises(PSTimetrackerParseError):
            parse_session({"playtime_id": 1, "start_local": "04/06/2024 20:00"})

    def test_parse_session_bool_duration_rejected(self) -> None:
        from my.ps_timetracker.common import PSTimetrackerParseError, parse_session

        with pytest.raises(PSTimetrackerParseError):
            parse_session({"playtime_id": 1, "duration_seconds": True})

    def test_parse_library_game(self) -> None:
        from my.ps_timetracker.common import parse_library_game

        g = parse_library_game(_sample_library_game())
        assert g.title == "Elden Ring"
        assert g.total_duration == timedelta(seconds=115500)
        assert g.total_duration_text == "32:05 hours"
        assert g.sessions_count == 48
        assert g.avg_session == timedelta(seconds=2406)
        assert g.last_played_local == datetime(2024, 4, 6, 21, 0)

    def test_parse_library_game_tolerates_weird_last_played(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Regression: real snapshots contain bare ``HH:MM`` in last_played_local
        (ps-timetracker renders recent plays as relative/time-only). That must
        leave the field None rather than nuke the whole library."""
        from my.ps_timetracker.common import parse_library_game

        with caplog.at_level("WARNING"):
            g = parse_library_game(
                _sample_library_game(last_played_local="1:20")
            )
        assert g.last_played_local is None
        assert g.title == "Elden Ring"  # rest of the row still parses
        assert any("1:20" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# export.py — driven through a fake harvester layout
# ---------------------------------------------------------------------------


class TestExportViaHarvester:
    def test_inputs_lists_snapshot_directories(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(tmp_path, "2024-04-06T03-00-00", sessions=[])

        from my.ps_timetracker import export

        inputs = list(export.inputs())
        assert len(inputs) == 1
        assert inputs[0].name == "2024-04-06T03-00-00"
        assert inputs[0].is_dir()

    def test_sessions_single_snapshot(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(
            tmp_path,
            "2024-04-06T03-00-00",
            sessions=[
                _sample_session(playtime_id=1, start_local="2024-04-06 20:00"),
                _sample_session(playtime_id=2, start_local="2024-04-05 19:00"),
            ],
        )

        from my.ps_timetracker import export
        from my.ps_timetracker.common import Session

        got = list(export.sessions())
        assert all(isinstance(s, Session) for s in got)
        assert [s.playtime_id for s in got] == [2, 1]  # chronological by start_local

    def test_sessions_deduped_across_snapshots_newer_wins(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        # Older snapshot: playtime 1 says "Elden Ring", 1 h.
        _write_snapshot(
            tmp_path,
            "2024-04-05T03-00-00",
            sessions=[
                _sample_session(
                    playtime_id=1, game_title="Elden Ring", duration_seconds=3600
                ),
            ],
        )
        # Newer snapshot: playtime 1 edited to "Elden Ring (edit)", 2 h.
        # Plus a new playtime 2.
        _write_snapshot(
            tmp_path,
            "2024-04-06T03-00-00",
            sessions=[
                _sample_session(
                    playtime_id=1,
                    game_title="Elden Ring (edit)",
                    duration_seconds=7200,
                ),
                _sample_session(
                    playtime_id=2,
                    game_title="Bloodborne",
                    start_local="2024-04-06 22:00",
                    end_local="2024-04-06 23:00",
                ),
            ],
        )

        from my.ps_timetracker import export
        from my.ps_timetracker.common import Session

        got = [s for s in export.sessions() if isinstance(s, Session)]
        by_id = {s.playtime_id: s for s in got}
        assert set(by_id) == {1, 2}
        assert by_id[1].game_title == "Elden Ring (edit)"
        assert by_id[1].duration == timedelta(hours=2)
        assert by_id[2].game_title == "Bloodborne"

    def test_bad_session_row_yielded_as_exception(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        snap = _write_snapshot(tmp_path, "2024-04-06T03-00-00")
        (snap / "sessions.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(_sample_session(playtime_id=1)),
                    "not even json",
                    json.dumps({"playtime_id": 2, "start_local": "bogus"}),
                ]
            )
            + "\n"
        )

        from my.ps_timetracker import export
        from my.ps_timetracker.common import Session

        got = list(export.sessions())
        # 1 valid Session + 2 exceptions (invalid JSON, bad datetime).
        sessions_ = [s for s in got if isinstance(s, Session)]
        errors = [e for e in got if isinstance(e, Exception)]
        assert len(sessions_) == 1
        assert len(errors) == 2

    def test_library_uses_latest_snapshot(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        # Older snapshot has a single game...
        _write_snapshot(
            tmp_path,
            "2024-04-05T03-00-00",
            library=[_sample_library_game(rank=1)],
            meta={
                "fetched_at_utc": "2024-04-05T03:00:00+00:00",
                "profile": "TrueNellrun",
            },
        )
        # ...newer snapshot has two: the library() call must see both.
        _write_snapshot(
            tmp_path,
            "2024-04-06T03-00-00",
            library=[
                _sample_library_game(rank=1),
                _sample_library_game(
                    rank=2, game_id="CUSA00001_00", game_title="Bloodborne"
                ),
            ],
            meta={
                "fetched_at_utc": "2024-04-06T03:00:00+00:00",
                "profile": "TrueNellrun",
            },
        )

        from my.ps_timetracker import export

        lib = export.library()
        assert lib.profile == "TrueNellrun"
        assert lib.fetched_at_utc == datetime(
            2024, 4, 6, 3, 0, tzinfo=timezone.utc
        )
        assert [g.title for g in lib.games] == ["Elden Ring", "Bloodborne"]

    def test_library_tolerates_missing_meta(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(
            tmp_path, "2024-04-06T03-00-00", library=[_sample_library_game()]
        )

        from my.ps_timetracker import export

        lib = export.library()
        assert lib.profile is None
        assert lib.fetched_at_utc is None
        assert len(lib.games) == 1

    def test_library_missing_raises(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        # An empty service dir means "no snapshots yet" — latest() raises.
        (tmp_path / "ps_timetracker").mkdir()

        from my.ps_timetracker import export

        with pytest.raises(FileNotFoundError):
            export.library()


# ---------------------------------------------------------------------------
# Facade (my.ps_timetracker.all) proxies to export
# ---------------------------------------------------------------------------


class TestAllFacade:
    def test_sessions_proxy(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(
            tmp_path,
            "2024-04-06T03-00-00",
            sessions=[_sample_session(playtime_id=1)],
        )

        from my.ps_timetracker import all as pst_all
        from my.ps_timetracker.common import Session

        got = list(pst_all.sessions())
        assert len(got) == 1 and isinstance(got[0], Session)

    def test_library_proxy(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(
            tmp_path,
            "2024-04-06T03-00-00",
            library=[_sample_library_game()],
            meta={"fetched_at_utc": "2024-04-06T03:00:00Z", "profile": "x"},
        )

        from my.ps_timetracker import all as pst_all

        lib = pst_all.library()
        assert lib.profile == "x"
        assert len(lib.games) == 1
