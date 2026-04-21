"""
Unified access to snapshots produced by `hpi-harvester`_.

This helper is the HPI-side of the harvester contract described in
``hpi-harvester/SPEC.md`` (section "Публичный контракт для потребителей").
It resolves snapshot paths from three configuration sources, in priority
order:

1. ``my.config.harvester.root`` — a single root directory produced by
   hpi-harvester. Snapshots for a source live under ``<root>/<source>/``.
   If the source directory contains ``_index.json``, it is used as a fast
   path; otherwise we fall back to globbing the directory.
2. ``my.config.<module>.export_path`` — the classic karlicoss/HPI
   configuration, preserved for backward compatibility when a module has
   pre-existing manual exports and no harvester instance to feed it.
3. Nothing configured — :class:`HarvesterConfigError` explains both options.

When both the harvester source name and the HPI module name differ (e.g. an
exporter named ``lastfm_karlicoss`` in the harvester YAML but
``my.lastfm.export`` on the HPI side), the module may set
``my.config.<module>.harvester_name`` to override the source name lookup
without changing the rest of the plumbing.

Consumers should never import from hpi-harvester directly; everything they
need is described by the manifest format and this helper.

.. _hpi-harvester: https://github.com/.../hpi-harvester
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Mirrors hpi-harvester/SPEC.md. Duplicated intentionally — the format is the
# contract, and we do not want an import dependency on the producer.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H-%M-%S"
_MANIFEST_FILENAME = "_index.json"
_SUPPORTED_SCHEMA_VERSION = 1


class HarvesterConfigError(Exception):
    """Raised when no snapshot source is configured for the requested source."""


@dataclass(frozen=True)
class SnapshotSet:
    """Immutable view of snapshots for a single source, sorted asc by timestamp.

    The set is a thin wrapper around a path tuple. Callers normally interact
    through :meth:`latest` or :meth:`all`; the container-like methods are
    provided for convenience (e.g. cachew ``depends_on=lambda: snapshot(...)``).
    """

    paths: tuple[Path, ...]
    source: str

    def latest(self) -> Path:
        """Return the freshest snapshot.

        Raises :class:`FileNotFoundError` when the set is empty — this matches
        the existing behaviour of ``my.letterboxd.export._latest`` so that
        HPI module authors can treat both code paths identically.
        """
        if not self.paths:
            raise FileNotFoundError(
                f"no snapshots found for source {self.source!r}; "
                f"check my.config.harvester.root or my.config.<module>.export_path"
            )
        return self.paths[-1]

    def all(self) -> list[Path]:
        """Return every snapshot path, sorted ascending (oldest → newest)."""
        return list(self.paths)

    def __iter__(self) -> Iterator[Path]:
        return iter(self.paths)

    def __len__(self) -> int:
        return len(self.paths)

    def __bool__(self) -> bool:
        return bool(self.paths)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def snapshot(
    source: str,
    *,
    module: Optional[str] = None,
    extensions: Optional[Iterable[str]] = None,
) -> SnapshotSet:
    """Resolve snapshots for ``source`` across every supported config shape.

    :param source: harvester source directory name (matches the ``name`` of
        an exporter in the harvester YAML). Used only when
        ``my.config.harvester.root`` is configured.
    :param module: short name of the calling HPI module (e.g. ``"lastfm"`` for
        ``my.lastfm.export``). Enables two optional behaviours:

        * reading ``my.config.<module>.harvester_name`` to override ``source``;
        * falling back to ``my.config.<module>.export_path`` when there is no
          harvester root.
    :param extensions: iterable of filename suffixes to accept (e.g.
        ``(".json",)``). Applied when globbing directly — files whose name
        does not end with any listed suffix are skipped. Directories and
        entries listed in a manifest are always accepted. When ``None``,
        every valid-timestamp entry is kept.
    """
    root = _load_harvester_root()
    if root is not None:
        effective_source = _resolve_source_name(source, module)
        service_dir = root / effective_source
        paths = _collect_from_harvester(service_dir, extensions)
        return SnapshotSet(paths=paths, source=effective_source)

    if module is not None:
        export_path = _load_module_export_path(module)
        if export_path is not None:
            paths = _collect_from_karlicoss(export_path)
            return SnapshotSet(paths=paths, source=module)

    raise HarvesterConfigError(
        _no_config_message(source=source, module=module)
    )


# ---------------------------------------------------------------------------
# Config lookup
# ---------------------------------------------------------------------------


def _load_harvester_root() -> Optional[Path]:
    """Return the user-configured harvester root, or ``None`` if unset."""
    try:
        from my.config import harvester as harvester_cfg  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        return None

    root = getattr(harvester_cfg, "root", None)
    if root is None:
        return None
    return Path(root).expanduser()


def _load_module_section(module: str) -> Optional[Any]:
    """Return ``my.config.<module>`` if present."""
    try:
        import my.config as cfg  # type: ignore[import-not-found]
    except ImportError:
        return None
    return getattr(cfg, module, None)


def _resolve_source_name(source: str, module: Optional[str]) -> str:
    """Apply ``my.config.<module>.harvester_name`` override if set."""
    if module is None:
        return source
    section = _load_module_section(module)
    if section is None:
        return source
    override = getattr(section, "harvester_name", None)
    if override is None:
        return source
    return str(override)


def _load_module_export_path(module: str) -> Optional[Any]:
    """Return ``my.config.<module>.export_path`` (karlicoss fallback)."""
    section = _load_module_section(module)
    if section is None:
        return None
    return getattr(section, "export_path", None)


# ---------------------------------------------------------------------------
# Harvester-produced layout
# ---------------------------------------------------------------------------


def _collect_from_harvester(
    service_dir: Path, extensions: Optional[Iterable[str]]
) -> tuple[Path, ...]:
    """Resolve snapshots inside a harvester-managed directory.

    Returns an empty tuple if the directory does not exist: that simply means
    no successful run has produced a snapshot yet.
    """
    if not service_dir.exists():
        return ()

    manifest_paths = _read_manifest(service_dir)
    if manifest_paths is None:
        # No manifest (or unreadable) — fall through to a plain directory scan.
        return tuple(_glob_service_dir(service_dir, extensions))

    # Reconcile manifest with disk:
    #   * drop manifest entries whose files were removed in the meantime;
    #   * pick up valid-timestamp files present on disk but missing from the
    #     (possibly stale) manifest.
    on_disk = {p.name: p for p in _glob_service_dir(service_dir, extensions)}
    result: list[Path] = []
    seen: set[str] = set()
    for entry in manifest_paths:
        if entry.exists():
            result.append(entry)
            seen.add(entry.name)
    for name, path in on_disk.items():
        if name not in seen:
            result.append(path)

    # Final sort by filename — the manifest is asc by timestamp, the reconciled
    # tail might not be, so we normalise. Timestamp format is lexicographic.
    return tuple(sorted(result, key=lambda p: p.name))


def _read_manifest(service_dir: Path) -> Optional[list[Path]]:
    """Return manifest-listed paths, or ``None`` if the manifest is unusable."""
    manifest_path = service_dir / _MANIFEST_FILENAME
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "failed to read %s (%s); falling back to directory scan",
            manifest_path,
            e,
        )
        return None

    version = data.get("schema_version")
    if version != _SUPPORTED_SCHEMA_VERSION:
        logger.warning(
            "unsupported manifest schema_version=%r at %s; falling back to "
            "directory scan",
            version,
            manifest_path,
        )
        return None

    entries = data.get("snapshots") or []
    return [service_dir / entry["path"] for entry in entries if "path" in entry]


def _glob_service_dir(
    service_dir: Path, extensions: Optional[Iterable[str]]
) -> list[Path]:
    """Scan ``service_dir`` for valid-timestamp snapshots."""
    if not service_dir.is_dir():
        return []

    normalised_exts: Optional[tuple[str, ...]] = (
        tuple(extensions) if extensions is not None else None
    )

    results: list[Path] = []
    for child in service_dir.iterdir():
        if child.name.startswith(".") or child.name == _MANIFEST_FILENAME:
            continue
        if child.is_dir():
            if _is_valid_timestamp(child.name):
                results.append(child)
            continue
        if child.is_file():
            if not _is_valid_timestamp(child.stem):
                continue
            if normalised_exts is not None and not _matches_extensions(
                child, normalised_exts
            ):
                continue
            results.append(child)
    results.sort(key=lambda p: p.name)
    return results


def _is_valid_timestamp(name: str) -> bool:
    """Return True when ``name`` matches the harvester timestamp format."""
    from datetime import datetime

    try:
        datetime.strptime(name, _TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True


def _matches_extensions(path: Path, extensions: tuple[str, ...]) -> bool:
    """Case-sensitive suffix match; leading dot is optional for callers."""
    normalised = tuple(
        ext if ext.startswith(".") else f".{ext}" for ext in extensions
    )
    return path.name.endswith(normalised)


# ---------------------------------------------------------------------------
# Karlicoss-compatible fallback
# ---------------------------------------------------------------------------


def _collect_from_karlicoss(export_path: Any) -> tuple[Path, ...]:
    """Resolve snapshots via the classic ``export_path`` configuration.

    Uses ``my.core.get_files`` so that any existing HPI user configuration
    (single path, glob, list of paths) keeps working unchanged.
    """
    from my.core import get_files  # type: ignore[import-not-found]

    return tuple(get_files(export_path))


# ---------------------------------------------------------------------------
# Error messages
# ---------------------------------------------------------------------------


def _no_config_message(*, source: str, module: Optional[str]) -> str:
    """Compose the diagnostic shown when neither config path is set."""
    lines = [
        f"No snapshot source is configured for source={source!r}.",
        "",
        "Configure one of the following in my.config:",
        "",
        "  # Option 1 (recommended) — set my.config.harvester.root to feed all modules:",
        "  class harvester:",
        "      root = '/path/to/harvester/data'",
    ]
    if module is not None:
        lines.extend(
            [
                "",
                f"  # Option 2 (karlicoss-compatible) — set my.config.{module}.export_path:",
                f"  class {module}:",
                f"      export_path = '/path/to/{source}/*'",
            ]
        )
    return "\n".join(lines)


__all__ = [
    "HarvesterConfigError",
    "SnapshotSet",
    "snapshot",
]
