"""Integration tests against a real export (both directory and ZIP layouts)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

# ``with_dir_config`` / ``with_zip_config`` are fixtures from conftest.py


def _import_export():
    # Import inside the function so the fixture has a chance to swap my.config
    # before the module is loaded.
    from my.letterboxd import export

    return export


class TestDiary:
    def test_dir(self, with_dir_config: Path) -> None:
        export = _import_export()
        entries = list(export.diary())

        # Nothing crashed
        assert all(not isinstance(e, Exception) for e in entries)
        assert len(entries) == 4

        # A fresh entry with a review is enriched from reviews.csv
        parasite = next(e for e in entries if e.film.name == "Parasite")  # type: ignore[union-attr]
        assert parasite.rating == 5.0
        assert parasite.review is not None
        assert "masterpiece" in parasite.review
        assert parasite.tags == ("oscars", "thriller")
        assert parasite.watched_date == date(2024, 1, 10)
        assert parasite.logged_date == date(2024, 1, 12)

        # Entry without a review -> review is None
        drive = next(e for e in entries if e.film.name == "Drive")  # type: ignore[union-attr]
        assert drive.review is None
        assert drive.rating is None  # empty cell -> None

        # rewatch=True
        matrix = next(e for e in entries if e.film.name == "The Matrix")  # type: ignore[union-attr]
        assert matrix.rewatch is True

    def test_zip(self, with_zip_config: Path) -> None:
        export = _import_export()
        entries = list(export.diary())
        assert len(entries) == 4
        assert all(not isinstance(e, Exception) for e in entries)


class TestReviews:
    def test_count_and_content(self, with_dir_config: Path) -> None:
        export = _import_export()
        revs = list(export.reviews())
        assert len(revs) == 2
        her = next(r for r in revs if r.film.name == "Her")  # type: ignore[union-attr]
        assert her.review and "Phoenix" in her.review


class TestRatings:
    def test_count(self, with_dir_config: Path) -> None:
        export = _import_export()
        rs = list(export.ratings())
        assert len(rs) == 3
        assert {r.film.name for r in rs if not isinstance(r, Exception)} == {  # type: ignore[union-attr]
            "The Matrix",
            "Parasite",
            "Her",
        }


class TestWatchedAndWatchlist:
    def test_watched(self, with_dir_config: Path) -> None:
        export = _import_export()
        ws = list(export.watched())
        assert len(ws) == 4

    def test_watchlist(self, with_dir_config: Path) -> None:
        export = _import_export()
        wl = list(export.watchlist())
        assert len(wl) == 2
        names = {w.film.name for w in wl if not isinstance(w, Exception)}  # type: ignore[union-attr]
        assert "Dune: Part Two" in names


class TestLikes:
    def test_likes(self, with_dir_config: Path) -> None:
        export = _import_export()
        ls = list(export.likes())
        assert len(ls) == 2


class TestFilms:
    def test_unique_films(self, with_dir_config: Path) -> None:
        export = _import_export()
        fs = list(export.films())
        # 4 unique watched + 2 unique on the watchlist = 6
        assert len({f.uri for f in fs}) == len(fs)
        assert len(fs) == 6


class TestStats:
    def test_stats_runs(self, with_dir_config: Path) -> None:
        export = _import_export()
        s = export.stats()
        # keys are strings with the function names
        assert {"diary", "reviews", "ratings", "watched", "watchlist", "likes"} <= set(s.keys())


class TestErrors:
    def test_missing_export_raises(self, tmp_path: Path) -> None:
        from tests.conftest import _install_fake_my_config, _reset_letterboxd_modules

        empty = tmp_path / "nothing"
        empty.mkdir()
        _install_fake_my_config(empty / "letterboxd-*.zip")
        _reset_letterboxd_modules()

        export = _import_export()
        with pytest.raises(FileNotFoundError):
            list(export.diary())
