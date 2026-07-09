"""
Freshness/cadence monitoring: alert when an expected file does NOT arrive.

Absence of data is the failure mode profiling can't catch — a feed that stops
sends nothing to profile. Each fileset's arrival cadence is learned from the
mtime history of its matched files (simple interval statistics, no model):
the median gap between consecutive arrivals is the expected cadence, and a
fileset is overdue when more than overdue_factor x median has passed since
the last arrival. Overdue filesets are reported as breaking fileset_overdue
events on every scan while the condition persists, so
`metahound changes --fail-on breaking` keeps gating until the feed recovers.

At least MIN_ARRIVALS distinct arrival times are required before a fileset is
judged at all — irregular young feeds stay silent, never false-positive.
"""
import datetime
import statistics

from metahound.diff import make_change
from metahound.filesets import fileset_uri

MIN_ARRIVALS = 3
DEFAULT_OVERDUE_FACTOR = 2.0


def evaluate_cadence(
    arrivals_by_fileset: dict,
    source_name: str,
    now: datetime.datetime | None = None,
    overdue_factor: float = DEFAULT_OVERDUE_FACTOR,
) -> list:
    """Return fileset_overdue events for filesets whose next file is late.

    arrivals_by_fileset: {fileset_name: [mtime, ...]} — order irrelevant,
    duplicates collapse (several files landing in one batch count as one
    arrival for interval purposes).
    """
    now = now or datetime.datetime.utcnow()
    events = []

    for fileset_name, mtimes in sorted(arrivals_by_fileset.items()):
        distinct = sorted(set(mtimes))
        if len(distinct) < MIN_ARRIVALS:
            continue

        intervals = [b - a for a, b in zip(distinct, distinct[1:])]
        median_interval = statistics.median(intervals)
        if median_interval <= datetime.timedelta(0):
            continue

        last_seen = distinct[-1]
        expected_by = last_seen + overdue_factor * median_interval
        if now <= expected_by:
            continue

        events.append(make_change(
            fileset_uri(source_name, fileset_name),
            "fileset_overdue",
            {
                "fileset": fileset_name,
                "last_seen": last_seen.isoformat(),
                "median_interval_seconds": int(median_interval.total_seconds()),
                "expected_by": expected_by.isoformat(),
                "overdue_seconds": int((now - expected_by).total_seconds()),
            },
        ))

    return events
