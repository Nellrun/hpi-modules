"""
HPI modules for the ``gwm-stats`` cross-platform gaming aggregator.

The aggregator (gowithme.club) pulls play sessions and trophies from PSN,
Steam, Nintendo and other backends and exposes them through per-tab
``/api/player*`` endpoints. The harvester-side ``gwm-stats-export`` tool
bundles them into one JSON snapshot per run.

Submodules:

* :mod:`my.gwm_stats.common` — shared domain models and JSON parsers.
* :mod:`my.gwm_stats.export` — reads file snapshots produced by the
  ``gwm_stats`` exporter in hpi-harvester. Sessions and trophies are
  merged across every snapshot and deduplicated; the game library and
  per-snapshot aggregates (top games, totals, breakdowns) come from the
  latest snapshot only.
* :mod:`my.gwm_stats.all` — combined facade; the stable entry point for
  end-user scripts.

Quick example::

    from my.gwm_stats.all import sessions, trophies, summary

    for s in sessions():
        if isinstance(s, Exception):
            continue
        print(s.started_at, s.title_name, s.duration)

    for t in trophies():
        if isinstance(t, Exception):
            continue
        print(t.earned_at, t.title_name, t.trophy_name)

    print(summary().totals.total_seconds, "seconds total")
"""

from __future__ import annotations

__all__ = [
    "all",
    "common",
    "export",
]
