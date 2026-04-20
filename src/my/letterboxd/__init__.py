"""
HPI modules for `Letterboxd <https://letterboxd.com>`_.

Submodules:

* :mod:`my.letterboxd.common`  — shared models and utilities.
* :mod:`my.letterboxd.export`  — parser for the official Letterboxd ZIP export.
* :mod:`my.letterboxd.all`     — combined source (defaults to ``export``;
  designed as an extension point for future sources: RSS, scraper, API, ...).

Quick example::

    from my.letterboxd.all import diary, ratings, watched

    for entry in diary():
        print(entry.watched_date, entry.film.name, entry.rating)

For full documentation and a configuration example, see the README.
"""

from __future__ import annotations

__all__ = [
    "all",
    "common",
    "export",
]
