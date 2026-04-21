"""Tests for ``my.harvester`` (snapshot resolver)."""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from my.harvester import HarvesterConfigError, SnapshotSet, snapshot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_config() -> Iterator[types.ModuleType]:
    """Install an empty ``my.config`` module for the duration of the test.

    Tests mutate it by assigning attribute classes (the same shape real
    users use in their ``~/.config/my/my/config/__init__.py``).
    """
    original = sys.modules.get("my.config")
    cfg = types.ModuleType("my.config")
    cfg.__path__ = []  # type: ignore[attr-defined]
    sys.modules["my.config"] = cfg
    try:
        yield cfg
    finally:
        if original is None:
            sys.modules.pop("my.config", None)
        else:
            sys.modules["my.config"] = original


def _set_root(cfg: types.ModuleType, root: Path) -> None:
    class harvester:  # noqa: N801 — matches user-facing config shape
        pass

    harvester.root = str(root)  # type: ignore[attr-defined]
    cfg.harvester = harvester  # type: ignore[attr-defined]


def _set_module_section(cfg: types.ModuleType, module: str, **attrs: object) -> None:
    section = types.SimpleNamespace(**attrs)
    setattr(cfg, module, section)


def _make_snapshot_file(service_dir: Path, name: str, body: str = "x") -> Path:
    service_dir.mkdir(parents=True, exist_ok=True)
    path = service_dir / name
    path.write_text(body)
    return path


def _make_snapshot_dir(service_dir: Path, name: str, files: dict[str, str]) -> Path:
    service_dir.mkdir(parents=True, exist_ok=True)
    path = service_dir / name
    path.mkdir()
    for fname, content in files.items():
        sub = path / fname
        sub.parent.mkdir(parents=True, exist_ok=True)
        sub.write_text(content)
    return path


def _write_manifest(
    service_dir: Path, exporter: str, entries: list[dict[str, object]]
) -> None:
    service_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "exporter": exporter,
        "updated_at": "2026-04-21T03:02:41Z",
        "snapshots": entries,
    }
    (service_dir / "_index.json").write_text(json.dumps(payload))


# ---------------------------------------------------------------------------
# No config at all
# ---------------------------------------------------------------------------


def test_no_config_raises(fake_config: types.ModuleType) -> None:
    with pytest.raises(HarvesterConfigError) as exc_info:
        snapshot("lastfm", module="lastfm")
    message = str(exc_info.value)
    assert "my.config.harvester" in message
    assert "my.config.lastfm" in message


def test_no_config_no_module_still_raises(fake_config: types.ModuleType) -> None:
    """Without ``module=``, the error mentions only the harvester option."""
    with pytest.raises(HarvesterConfigError) as exc_info:
        snapshot("lastfm")
    # The karlicoss-specific hint is omitted when we don't know the module.
    assert "my.config.harvester" in str(exc_info.value)


# ---------------------------------------------------------------------------
# harvester.root mode — with manifest
# ---------------------------------------------------------------------------


def test_root_with_manifest_returns_listed_snapshots(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    _set_root(fake_config, tmp_path)
    service = tmp_path / "lastfm"
    a = _make_snapshot_file(service, "2026-04-18T03-00-00.json", "a")
    b = _make_snapshot_file(service, "2026-04-20T03-00-00.json", "bb")
    _write_manifest(
        service,
        "lastfm",
        [
            {"timestamp": "2026-04-18T03-00-00", "path": a.name, "type": "file", "size_bytes": 1},
            {"timestamp": "2026-04-20T03-00-00", "path": b.name, "type": "file", "size_bytes": 2},
        ],
    )

    result = snapshot("lastfm", module="lastfm")
    assert result.all() == [a, b]
    assert result.latest() == b
    assert result.source == "lastfm"


def test_root_manifest_drops_missing_files(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    """If manifest references a file that was removed manually — drop it."""
    _set_root(fake_config, tmp_path)
    service = tmp_path / "lastfm"
    existing = _make_snapshot_file(service, "2026-04-20T03-00-00.json")
    _write_manifest(
        service,
        "lastfm",
        [
            {"timestamp": "2026-04-18T03-00-00", "path": "2026-04-18T03-00-00.json", "type": "file", "size_bytes": 1},
            {"timestamp": "2026-04-20T03-00-00", "path": existing.name, "type": "file", "size_bytes": 1},
        ],
    )

    result = snapshot("lastfm", module="lastfm")
    assert result.all() == [existing]


def test_root_manifest_adds_disk_extras(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    """Files on disk but absent from the manifest are still returned."""
    _set_root(fake_config, tmp_path)
    service = tmp_path / "lastfm"
    listed = _make_snapshot_file(service, "2026-04-18T03-00-00.json")
    extra = _make_snapshot_file(service, "2026-04-20T03-00-00.json")
    _write_manifest(
        service,
        "lastfm",
        [
            {"timestamp": "2026-04-18T03-00-00", "path": listed.name, "type": "file", "size_bytes": 1},
        ],
    )

    result = snapshot("lastfm", module="lastfm")
    # Sorted ascending by filename (== timestamp).
    assert result.all() == [listed, extra]
    assert result.latest() == extra


def test_root_manifest_unsupported_version_falls_back(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    _set_root(fake_config, tmp_path)
    service = tmp_path / "lastfm"
    snap = _make_snapshot_file(service, "2026-04-20T03-00-00.json")
    (service / "_index.json").write_text(
        json.dumps({"schema_version": 999, "exporter": "lastfm", "snapshots": []})
    )

    result = snapshot("lastfm", module="lastfm", extensions=(".json",))
    # Fallback globbed the directory and found the file.
    assert result.all() == [snap]


def test_root_manifest_invalid_json_falls_back(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    _set_root(fake_config, tmp_path)
    service = tmp_path / "lastfm"
    snap = _make_snapshot_file(service, "2026-04-20T03-00-00.json")
    (service / "_index.json").write_text("not json at all {{{")

    result = snapshot("lastfm", module="lastfm", extensions=(".json",))
    assert result.all() == [snap]


# ---------------------------------------------------------------------------
# harvester.root mode — without manifest (glob fallback)
# ---------------------------------------------------------------------------


def test_root_glob_sorts_ascending(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    _set_root(fake_config, tmp_path)
    service = tmp_path / "lastfm"
    _make_snapshot_file(service, "2026-04-20T03-00-00.json")
    _make_snapshot_file(service, "2026-04-18T03-00-00.json")
    _make_snapshot_file(service, "2026-04-19T03-00-00.json")

    result = snapshot("lastfm", module="lastfm", extensions=(".json",))
    assert [p.name for p in result.all()] == [
        "2026-04-18T03-00-00.json",
        "2026-04-19T03-00-00.json",
        "2026-04-20T03-00-00.json",
    ]


def test_root_glob_filters_by_extension(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    _set_root(fake_config, tmp_path)
    service = tmp_path / "lastfm"
    keep = _make_snapshot_file(service, "2026-04-20T03-00-00.json")
    _make_snapshot_file(service, "2026-04-20T03-00-01.csv")  # different extension

    result = snapshot("lastfm", module="lastfm", extensions=(".json",))
    assert result.all() == [keep]


def test_root_glob_skips_spurious_and_hidden(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    _set_root(fake_config, tmp_path)
    service = tmp_path / "lastfm"
    good = _make_snapshot_file(service, "2026-04-20T03-00-00.json")
    _make_snapshot_file(service, "README.md")  # unparseable timestamp
    _make_snapshot_file(service, ".2026-04-22T03-00-00.json.tmp")  # hidden

    result = snapshot("lastfm", module="lastfm", extensions=(".json",))
    assert result.all() == [good]


def test_root_glob_accepts_directory_snapshots(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    _set_root(fake_config, tmp_path)
    service = tmp_path / "dump"
    snap = _make_snapshot_dir(service, "2026-04-20T03-00-00", {"a.txt": "1"})

    # extensions argument must not prevent directories from being listed.
    result = snapshot("dump", module="dump", extensions=(".json",))
    assert result.all() == [snap]


def test_root_glob_accepts_extension_without_leading_dot(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    _set_root(fake_config, tmp_path)
    service = tmp_path / "lastfm"
    snap = _make_snapshot_file(service, "2026-04-20T03-00-00.json")

    result = snapshot("lastfm", module="lastfm", extensions=("json",))
    assert result.all() == [snap]


def test_root_missing_service_dir_yields_empty_set(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    _set_root(fake_config, tmp_path)
    result = snapshot("neverran", module="neverran")
    assert result.all() == []
    assert not result
    with pytest.raises(FileNotFoundError):
        result.latest()


# ---------------------------------------------------------------------------
# harvester_name override
# ---------------------------------------------------------------------------


def test_harvester_name_override_redirects_lookup(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    """``my.config.<module>.harvester_name`` points at a differently-named source."""
    _set_root(fake_config, tmp_path)
    actual_service = tmp_path / "lastfm_karlicoss"
    _make_snapshot_file(actual_service, "2026-04-20T03-00-00.json")
    # The module is ``my.lastfm`` but the harvester YAML named the source
    # ``lastfm_karlicoss``, so we redirect via the config.
    _set_module_section(fake_config, "lastfm", harvester_name="lastfm_karlicoss")

    result = snapshot("lastfm", module="lastfm", extensions=(".json",))
    assert [p.parent.name for p in result.all()] == ["lastfm_karlicoss"]
    assert result.source == "lastfm_karlicoss"


def test_harvester_name_override_only_takes_effect_with_module(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    """Without ``module=``, there's no per-module config to read."""
    _set_root(fake_config, tmp_path)
    _make_snapshot_file(tmp_path / "lastfm", "2026-04-20T03-00-00.json")
    # Even though a section exists, we don't know which one to read.
    _set_module_section(fake_config, "lastfm", harvester_name="OTHER")

    result = snapshot("lastfm", extensions=(".json",))
    assert result.source == "lastfm"


# ---------------------------------------------------------------------------
# karlicoss-compatible fallback
# ---------------------------------------------------------------------------


def test_karlicoss_fallback_uses_export_path(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    # No harvester root configured at all.
    data_dir = tmp_path / "legacy"
    data_dir.mkdir()
    (data_dir / "a.json").write_text("1")
    (data_dir / "b.json").write_text("2")

    _set_module_section(fake_config, "lastfm", export_path=str(data_dir / "*.json"))

    result = snapshot("lastfm", module="lastfm")
    names = [p.name for p in result.all()]
    assert names == ["a.json", "b.json"]  # get_files sorts ascending


def test_karlicoss_fallback_requires_module(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    # Without module=, we have no way to know which my.config section to read.
    (tmp_path / "x.json").write_text("1")
    _set_module_section(fake_config, "lastfm", export_path=str(tmp_path / "*.json"))

    with pytest.raises(HarvesterConfigError):
        snapshot("lastfm")


def test_harvester_root_wins_over_export_path(
    fake_config: types.ModuleType, tmp_path: Path
) -> None:
    """If both configs are set, the harvester root takes priority."""
    root = tmp_path / "harvester"
    new_snap = _make_snapshot_file(root / "lastfm", "2026-04-20T03-00-00.json")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "old.json").write_text("1")

    _set_root(fake_config, root)
    _set_module_section(fake_config, "lastfm", export_path=str(legacy / "*.json"))

    result = snapshot("lastfm", module="lastfm", extensions=(".json",))
    assert result.all() == [new_snap]


# ---------------------------------------------------------------------------
# SnapshotSet API
# ---------------------------------------------------------------------------


def test_snapshotset_container_protocol() -> None:
    paths = (Path("/a/2026-04-18T03-00-00.json"), Path("/a/2026-04-20T03-00-00.json"))
    s = SnapshotSet(paths=paths, source="lastfm")

    assert len(s) == 2
    assert bool(s) is True
    assert list(iter(s)) == list(paths)
    assert s.all() == list(paths)
    assert s.latest() == paths[-1]


def test_snapshotset_empty() -> None:
    s = SnapshotSet(paths=(), source="x")
    assert len(s) == 0
    assert bool(s) is False
    with pytest.raises(FileNotFoundError):
        s.latest()


# ---------------------------------------------------------------------------
# Root expansion
# ---------------------------------------------------------------------------


def test_harvester_root_expanduser(
    fake_config: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``~`` in the configured root is expanded like every HPI config path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    service = tmp_path / "harvester_data" / "lastfm"
    snap = _make_snapshot_file(service, "2026-04-20T03-00-00.json")

    class harvester:
        root = "~/harvester_data"

    fake_config.harvester = harvester  # type: ignore[attr-defined]

    result = snapshot("lastfm", module="lastfm", extensions=(".json",))
    assert result.all() == [snap]
