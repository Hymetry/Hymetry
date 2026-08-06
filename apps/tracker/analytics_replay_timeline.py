"""Compatibility entry point for the analytical replay control.

The underlying projection is shared with Visits and owns its own analytical
clock.  rrweb bounds must never be passed into or applied by this module.
"""

from apps.tracker.analytics_visit_projection import (
    ANALYTICS_ACTIVE_GAP_CAP_MS,
    ANALYTICS_VISIT_SOURCE,
    build_analytics_visit_projection,
)


ANALYTICS_REPLAY_ACTIVE_GAP_CAP_MS = ANALYTICS_ACTIVE_GAP_CAP_MS
ANALYTICS_REPLAY_SOURCE = ANALYTICS_VISIT_SOURCE


def build_analytics_replay_timeline(project, session):
    """Return the canonical analytical visit projection for replay controls."""

    return build_analytics_visit_projection(project, session)
