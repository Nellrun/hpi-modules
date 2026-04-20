"""
Shared test infrastructure.

Also installs an in-memory fake ``my.config.letterboxd`` so the tests don't
depend on the user's real configuration.
"""

from __future__ import annotations

import os
import shutil
import sys
import types
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTDATA = REPO_ROOT / "testdata" / "letterboxd-export-sample"


def _install_fake_my_config(export_path: Path) -> None:
    """Set ``my.config.letterboxd.export_path`` to our test path.

    We prefer a clean in-memory implementation over ``MY_CONFIG`` pointing at
    a temp directory: it's faster and more hermetic.
    """
    cfg_pkg = sys.modules.get("my.config")
    if cfg_pkg is None:
        cfg_pkg = types.ModuleType("my.config")
        cfg_pkg.__path__ = []  # type: ignore[attr-defined]
        sys.modules["my.config"] = cfg_pkg

    class letterboxd:
        pass

    letterboxd.export_path = str(export_path)  # type: ignore[attr-defined]
    cfg_pkg.letterboxd = letterboxd  # type: ignore[attr-defined]

    # Disable cachew so tests don't try to write outside the working directory.
    class core:
        cache_dir = None  # signal value -> cachew is a no-op

    cfg_pkg.core = core  # type: ignore[attr-defined]


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    """A copy of the sample export laid out as an unpacked directory."""
    dst = tmp_path / "letterboxd-export"
    shutil.copytree(TESTDATA, dst)
    return dst


@pytest.fixture
def sample_zip(tmp_path: Path) -> Path:
    """A copy of the sample export packaged as a ZIP (the real Letterboxd format)."""
    zip_path = tmp_path / "letterboxd-export.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(TESTDATA):
            for name in files:
                full = Path(root) / name
                arcname = full.relative_to(TESTDATA).as_posix()
                zf.write(full, arcname)
    return zip_path


@pytest.fixture
def with_dir_config(sample_dir: Path) -> Path:
    _install_fake_my_config(sample_dir)
    _reset_letterboxd_modules()
    return sample_dir


@pytest.fixture
def with_zip_config(sample_zip: Path) -> Path:
    _install_fake_my_config(sample_zip)
    _reset_letterboxd_modules()
    return sample_zip


def _reset_letterboxd_modules() -> None:
    """Drop cached modules so the new config takes effect on next import."""
    for name in list(sys.modules):
        if name.startswith("my.letterboxd"):
            del sys.modules[name]
