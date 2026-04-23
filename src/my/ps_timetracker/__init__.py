"""
HPI modules for `ps-timetracker.com <https://ps-timetracker.com>`_ — an
unofficial PlayStation playtime tracker that monitors PSN friend-presence
(no PSN password or NPSSO required).

Submodules:

* :mod:`my.ps_timetracker.common` — shared domain models and JSON parsers.
* :mod:`my.ps_timetracker.export` — reads directory snapshots produced by
  the ``ps_timetracker`` exporter in hpi-harvester and merges per-run
  ``sessions.jsonl`` chunks into a deduplicated stream keyed by
  ``playtime_id``.
* :mod:`my.ps_timetracker.all` — combined facade; the stable entry point
  for end-user scripts.

Quick example::

    from my.ps_timetracker.all import sessions, library

    for s in sessions():
        if isinstance(s, Exception):
            continue
        print(s.start_local, s.game_title, s.duration)

    for game in library().games:
        print(game.title, game.total_duration, game.sessions_count)

For setup and configuration, see the README.
"""

from __future__ import annotations

__all__ = [
    "all",
    "common",
    "export",
]
