"""Unit tests for the pure functions in ``my.letterboxd.common``."""

from __future__ import annotations

from datetime import date

import pytest

from my.letterboxd.common import (
    Film,
    LetterboxdParseError,
    parse_bool_yes,
    parse_date,
    parse_rating,
    parse_tags,
    parse_year,
)


class TestParseRating:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("0.5", 0.5),
            ("3", 3.0),
            ("5.0", 5.0),
            ("", None),
            ("   ", None),
        ],
    )
    def test_valid(self, raw: str, expected: float | None) -> None:
        assert parse_rating(raw) == expected

    @pytest.mark.parametrize("raw", ["6", "-1", "abc"])
    def test_invalid(self, raw: str) -> None:
        with pytest.raises(LetterboxdParseError):
            parse_rating(raw)


class TestParseDate:
    def test_valid(self) -> None:
        assert parse_date("2024-01-12") == date(2024, 1, 12)

    def test_empty(self) -> None:
        assert parse_date("") is None
        assert parse_date("   ") is None

    def test_invalid(self) -> None:
        with pytest.raises(ValueError, match="Invalid isoformat"):
            parse_date("not-a-date")


def test_parse_year() -> None:
    assert parse_year("1999") == 1999
    assert parse_year("") is None


def test_parse_bool_yes() -> None:
    assert parse_bool_yes("Yes") is True
    assert parse_bool_yes("yes") is True
    assert parse_bool_yes("") is False
    assert parse_bool_yes("No") is False


def test_parse_tags() -> None:
    assert parse_tags("") == ()
    assert parse_tags("oscars") == ("oscars",)
    assert parse_tags("oscars,thriller, art house") == ("oscars", "thriller", "art house")


def test_film_slug() -> None:
    f = Film(name="Parasite", year=2019, uri="https://letterboxd.com/film/parasite-2019/")
    assert f.slug == "parasite-2019"
