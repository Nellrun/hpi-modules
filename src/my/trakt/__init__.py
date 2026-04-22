"""
HPI modules for `Trakt.tv <https://trakt.tv>`_.

Submodules:

* :mod:`my.trakt.common` — shared domain models and JSON parsers.
* :mod:`my.trakt.export` — parser for the ``traktexport export`` JSON dump,
  driven by the hpi-harvester snapshot contract (see :mod:`my.harvester`).
* :mod:`my.trakt.all`    — combined facade; the stable entry point for
  end-user scripts.

Quick example::

    from my.trakt.all import history

    for entry in history():
        if isinstance(entry, Exception):
            continue
        print(entry.watched_at, entry.media_type, entry.media_data)

For setup and configuration, see the README.
"""

from __future__ import annotations

__all__ = [
    "all",
    "common",
    "export",
]
