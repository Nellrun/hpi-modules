"""Tests for the ``my.gwm_stats`` modules."""

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
    _reset_modules()
    try:
        yield cfg
    finally:
        if original is None:
            sys.modules.pop("my.config", None)
        else:
            sys.modules["my.config"] = original
        _reset_modules()


def _reset_modules() -> None:
    for name in list(sys.modules):
        if name.startswith("my.gwm_stats"):
            del sys.modules[name]


def _set_harvester_root(cfg: types.ModuleType, root: Path) -> None:
    class harvester:
        pass

    harvester.root = str(root)  # type: ignore[attr-defined]
    cfg.harvester = harvester  # type: ignore[attr-defined]


def _write_snapshot(root: Path, timestamp: str, payload: dict) -> Path:
    service = root / "gwm_stats"
    service.mkdir(parents=True, exist_ok=True)
    path = service / f"{timestamp}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _session_row(
    *,
    title_id: str = "CUSA18774_00",
    title_name: str = "NieR Replicant ver.1.22474487139...",
    platform: str = "PS5",
    source: str = "psn",
    started_at: str = "2026-06-21T19:42:10.289Z",
    ended_at: str | None = "2026-06-21T21:32:06.831Z",
    observed_seconds: int | None = 6576,
) -> dict:
    return {
        "title_id": title_id,
        "title_name": title_name,
        "platform": platform,
        "source": source,
        "started_at": started_at,
        "ended_at": ended_at,
        "observed_seconds": observed_seconds,
    }


def _trophy_row(
    *,
    np_comm_id: str = "NPWR19895_00",
    trophy_id: int = 36,
    source: str = "psn",
    earned_at: str = "2026-06-21T20:45:43.000Z",
    trophy_name: str = "Boss of the Junk Heap",
    is_self: int = 0,
    trophy_hidden: int = 0,
    rarity: float = 17.3,
) -> dict:
    return {
        "account_id": "3591785894479291112",
        "online_id": "TrueNellrun",
        "is_self": is_self,
        "np_comm_id": np_comm_id,
        "trophy_id": trophy_id,
        "source": source,
        "trophy_key": None,
        "title_name": "NieR Replicant ver.1.22474487139...",
        "trophy_name": trophy_name,
        "trophy_detail": "You defeated P-33 within four and a half minutes.",
        "trophy_type": "bronze",
        "trophy_hidden": trophy_hidden,
        "rarity": rarity,
        "icon_url": "https://image.api.playstation.com/trophy/.../foo.png",
        "earned_at": earned_at,
        "display_name": "Nellrun",
    }


def _full_payload(**overrides) -> dict:
    base: dict = {
        "name": "Nellrun",
        "memberCount": 5,
        "playerName": "Nellrun",
        "isSelf": False,
        "totals": {
            "total_seconds": 105853,
            "sessions": 16,
            "games": 5,
            "avg_session_seconds": 6615.8125,
            "longest_session_seconds": 17243,
            "first_started_at": "2026-06-17T13:49:13.734Z",
            "last_ended_at": "2026-06-21T21:32:06.831Z",
        },
        "topGames": [
            {
                "title_id": "CUSA18774_00",
                "title_name": "NieR Replicant ver.1.22474487139...",
                "platform": "PS5",
                "total_seconds": 64432,
                "sessions": 7,
                "source": "psn",
            }
        ],
        "byWeekday": [],
        "byMonth": [],
        "peakDay": None,
        "platformBreakdown": [
            {"source": "psn", "total_seconds": 90082, "sessions": 13, "games": 3},
            {"source": "steam", "total_seconds": 10016, "sessions": 2, "games": 1},
        ],
        "sessionsLog": [_session_row()],
        "trophies": [_trophy_row()],
    }
    base.update(overrides)
    return base


def _game_row(**overrides) -> dict:
    base: dict = {
        "title_id": "steam:238960",
        "title_name": "Path of Exile",
        "source": "steam",
        "sources": ["psn", "steam"],
        "total_seconds": 4878686,
        "observed_seconds": 0,
        "sessions": 0,
        "play_count": 13,
        "players": 1,
        "lastPlayedAt": "2024-11-21T22:15:37.550Z",
        "igdb_game_id": 1911,
        "coverUrl": "https://images.igdb.com/igdb/image/upload/t_original/co1n6w.jpg",
        "iconUrl": "/api/game-artwork/2710/icon-1778.ico",
        "editionSlug": None,
        "platforms": [
            {"source": "steam", "total_seconds": 4868460},
            {"source": "psn", "total_seconds": 10226},
        ],
    }
    base.update(overrides)
    return base


def _envelope_payload(
    *,
    sessions: list[dict] | None = None,
    trophies: list[dict] | None = None,
    games: list[dict] | None = None,
    include_trophies: bool = True,
) -> dict:
    """Current exporter layout: per-endpoint sections bundled together."""
    profile = _full_payload(gameTotal=422, trophyTotal=5869, platinumTotal=8)
    profile["totals"] = {**profile["totals"], "active_days": 90}
    # /api/player truncates these to a single page.
    profile["sessionsLog"] = []
    profile["trophies"] = [_trophy_row(trophy_id=1)]
    payload: dict = {
        "fetched_at": "2026-09-23T10:32:20.217479+00:00",
        "name": "Nellrun",
        "aliases": [],
        "profile": profile,
        "activity": {
            "section": "activity",
            "sessionsLog": [_session_row()] if sessions is None else sessions,
        },
        "games": [_game_row()] if games is None else games,
    }
    if include_trophies:
        payload["trophies"] = [_trophy_row()] if trophies is None else trophies
    return payload


# ---------------------------------------------------------------------------
# common.py — pure parsers
# ---------------------------------------------------------------------------


class TestCommon:
    def test_parse_session_full(self) -> None:
        from my.gwm_stats.common import Session, parse_session

        s = parse_session(_session_row())
        assert isinstance(s, Session)
        assert s.title_id == "CUSA18774_00"
        assert s.title_name.startswith("NieR")
        assert s.platform == "PS5"
        assert s.source == "psn"
        assert s.started_at == datetime(2026, 6, 21, 19, 42, 10, 289000, tzinfo=timezone.utc)
        assert s.ended_at == datetime(2026, 6, 21, 21, 32, 6, 831000, tzinfo=timezone.utc)
        assert s.duration == timedelta(seconds=6576)

    def test_parse_session_missing_required(self) -> None:
        from my.gwm_stats.common import GwmStatsParseError, parse_session

        with pytest.raises(GwmStatsParseError):
            parse_session({"source": "psn", "started_at": "2026-06-21T19:42:10Z"})
        with pytest.raises(GwmStatsParseError):
            parse_session({"title_id": "x", "source": "psn"})

    def test_parse_session_bad_datetime(self) -> None:
        from my.gwm_stats.common import GwmStatsParseError, parse_session

        with pytest.raises(GwmStatsParseError):
            parse_session(_session_row(started_at="06/21/2026"))

    def test_parse_trophy(self) -> None:
        from my.gwm_stats.common import parse_trophy

        t = parse_trophy(_trophy_row())
        assert t.trophy_id == 36
        assert t.source == "psn"
        assert t.trophy_hidden is False  # 0 → False
        assert t.rarity == 17.3
        assert t.earned_at == datetime(2026, 6, 21, 20, 45, 43, tzinfo=timezone.utc)

    def test_parse_trophy_hidden_one_means_true(self) -> None:
        from my.gwm_stats.common import parse_trophy

        t = parse_trophy(_trophy_row(trophy_hidden=1))
        assert t.trophy_hidden is True

    def test_parse_totals_empty(self) -> None:
        from my.gwm_stats.common import parse_totals

        t = parse_totals(None)
        assert t.total_duration is None
        assert t.sessions_count is None

    def test_parse_game(self) -> None:
        from my.gwm_stats.common import parse_game

        g = parse_game(_game_row())
        assert g.title_id == "steam:238960"
        assert g.sources == ("psn", "steam")
        assert g.total_duration == timedelta(seconds=4878686)
        assert g.observed_duration == timedelta(0)
        assert g.play_count == 13
        assert g.igdb_game_id == 1911
        assert g.last_played_at == datetime(2024, 11, 21, 22, 15, 37, 550000, tzinfo=timezone.utc)
        assert [(p.source, p.total_duration) for p in g.platforms] == [
            ("steam", timedelta(seconds=4868460)),
            ("psn", timedelta(seconds=10226)),
        ]

    def test_parse_game_missing_title_id(self) -> None:
        from my.gwm_stats.common import GwmStatsParseError, parse_game

        with pytest.raises(GwmStatsParseError):
            parse_game(_game_row(title_id=None))


# ---------------------------------------------------------------------------
# export.py — driven through a fake harvester layout
# ---------------------------------------------------------------------------


class TestExportViaHarvester:
    def test_inputs_lists_snapshot_files(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(tmp_path, "2026-06-19T03-00-00", _full_payload())
        _write_snapshot(tmp_path, "2026-06-20T03-00-00", _full_payload())

        from my.gwm_stats import export

        paths = list(export.inputs())
        assert [p.name for p in paths] == [
            "2026-06-19T03-00-00.json",
            "2026-06-20T03-00-00.json",
        ]

    def test_sessions_dedup_across_snapshots(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        # Same (title_id, started_at, source) in both snapshots: newer wins.
        old = _session_row(observed_seconds=1000)
        new = _session_row(observed_seconds=6576)
        extra = _session_row(
            title_id="PPSA10664_00",
            title_name="FINAL FANTASY XVI",
            started_at="2026-06-18T15:31:57.895Z",
            ended_at="2026-06-18T16:44:09.202Z",
            observed_seconds=4323,
        )
        _write_snapshot(
            tmp_path,
            "2026-06-20T03-00-00",
            _full_payload(sessionsLog=[old, extra]),
        )
        _write_snapshot(
            tmp_path,
            "2026-06-21T03-00-00",
            _full_payload(sessionsLog=[new]),
        )

        from my.gwm_stats import export

        result = [s for s in export.sessions() if not isinstance(s, Exception)]
        # 2 unique sessions
        assert len(result) == 2
        # Newer version wins
        nier = next(s for s in result if s.title_id == "CUSA18774_00")
        assert nier.duration == timedelta(seconds=6576)
        # Chronological order
        assert result[0].started_at < result[1].started_at

    def test_trophies_dedup_and_sort(self, fake_config: types.ModuleType, tmp_path: Path) -> None:
        _set_harvester_root(fake_config, tmp_path)
        t1 = _trophy_row(trophy_id=36, earned_at="2026-06-21T20:45:43.000Z")
        t2 = _trophy_row(
            trophy_id=19,
            earned_at="2026-06-20T23:39:59.000Z",
            trophy_name="Call Her Back",
        )
        # second snapshot repeats t1 — dedup should keep it once
        _write_snapshot(tmp_path, "2026-06-20T03-00-00", _full_payload(trophies=[t2]))
        _write_snapshot(tmp_path, "2026-06-21T03-00-00", _full_payload(trophies=[t1, t2]))

        from my.gwm_stats import export

        rows = [t for t in export.trophies() if not isinstance(t, Exception)]
        assert [t.trophy_id for t in rows] == [19, 36]

    def test_summary_uses_latest_snapshot(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        old_payload = _full_payload()
        old_payload["totals"] = {**old_payload["totals"], "sessions": 1}
        _write_snapshot(tmp_path, "2026-06-19T03-00-00", old_payload)
        _write_snapshot(tmp_path, "2026-06-21T03-00-00", _full_payload())

        from my.gwm_stats import export

        s = export.summary()
        assert s.name == "Nellrun"
        assert s.totals.sessions_count == 16  # latest, not 1
        assert s.totals.total_duration == timedelta(seconds=105853)
        assert s.totals.longest_session == timedelta(seconds=17243)
        assert len(s.top_games) == 1
        assert s.top_games[0].title_id == "CUSA18774_00"
        assert [p.source for p in s.platform_breakdown] == ["psn", "steam"]

    def test_summary_raises_when_no_snapshots(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        # No snapshots written.
        from my.gwm_stats import export

        with pytest.raises(FileNotFoundError):
            export.summary()

    def test_corrupt_snapshot_yields_exception_not_crash(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        (tmp_path / "gwm_stats").mkdir(parents=True, exist_ok=True)
        bad = tmp_path / "gwm_stats" / "2026-06-21T03-00-00.json"
        bad.write_text("not json at all", encoding="utf-8")
        _write_snapshot(tmp_path, "2026-06-22T03-00-00", _full_payload())

        from my.gwm_stats import export

        results = list(export.sessions())
        errors = [r for r in results if isinstance(r, Exception)]
        ok = [r for r in results if not isinstance(r, Exception)]
        assert len(errors) >= 1
        assert len(ok) >= 1  # the good snapshot still parsed


class TestEnvelopeSnapshots:
    """Snapshots written after the site split ``/api/player`` into per-tab
    endpoints, mixed with legacy ones."""

    def test_sessions_come_from_activity_and_merge_with_legacy(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        legacy = _session_row(
            title_id="PPSA10664_00",
            started_at="2026-06-18T15:31:57.895Z",
            observed_seconds=4323,
        )
        _write_snapshot(tmp_path, "2026-06-20T03-00-00", _full_payload(sessionsLog=[legacy]))
        _write_snapshot(
            tmp_path,
            "2026-09-23T10-32-03",
            _envelope_payload(sessions=[legacy, _session_row()]),
        )

        from my.gwm_stats import export

        result = [s for s in export.sessions() if not isinstance(s, Exception)]
        assert [s.title_id for s in result] == ["PPSA10664_00", "CUSA18774_00"]

    def test_trophies_use_full_log(self, fake_config: types.ModuleType, tmp_path: Path) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(
            tmp_path,
            "2026-09-23T10-32-03",
            _envelope_payload(trophies=[_trophy_row(trophy_id=36), _trophy_row(trophy_id=37)]),
        )

        from my.gwm_stats import export

        rows = [t for t in export.trophies() if not isinstance(t, Exception)]
        # Not profile's truncated page (trophy_id=1).
        assert sorted(t.trophy_id for t in rows) == [36, 37]

    def test_trophies_fall_back_to_profile_page(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(tmp_path, "2026-09-23T10-32-03", _envelope_payload(include_trophies=False))

        from my.gwm_stats import export

        rows = [t for t in export.trophies() if not isinstance(t, Exception)]
        assert [t.trophy_id for t in rows] == [1]

    def test_summary_reads_profile(self, fake_config: types.ModuleType, tmp_path: Path) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(tmp_path, "2026-09-23T10-32-03", _envelope_payload())

        from my.gwm_stats import export

        s = export.summary()
        assert s.fetched_at_utc == datetime(2026, 9, 23, 10, 32, 20, 217479, tzinfo=timezone.utc)
        assert s.name == "Nellrun"
        assert s.totals.sessions_count == 16
        assert s.totals.active_days == 90
        assert [p.source for p in s.platform_breakdown] == ["psn", "steam"]
        assert (s.game_total, s.trophy_total, s.platinum_total) == (422, 5869, 8)

    def test_games_from_latest_snapshot(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(
            tmp_path, "2026-09-22T03-00-00", _envelope_payload(games=[_game_row(title_id="old")])
        )
        _write_snapshot(tmp_path, "2026-09-23T10-32-03", _envelope_payload())

        from my.gwm_stats import export

        assert [g.title_id for g in export.games()] == ["steam:238960"]

    def test_games_empty_for_legacy_snapshot(
        self, fake_config: types.ModuleType, tmp_path: Path
    ) -> None:
        _set_harvester_root(fake_config, tmp_path)
        _write_snapshot(tmp_path, "2026-06-21T03-00-00", _full_payload())

        from my.gwm_stats import export

        assert list(export.games()) == []
