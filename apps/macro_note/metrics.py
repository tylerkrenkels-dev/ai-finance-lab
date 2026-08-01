"""Builds Metric objects from stored Observation history for one series at a time.

Sits between calculations/ and payload.py: reads from ObservationStore, applies
the staleness rule, and runs changes.py's three horizon functions, producing a
single Metric ready for NoteFacts assembly. Not itself a pure function (it
reads the store), so it doesn't live in calculations/ -- but it takes note_date
as an explicit parameter rather than reading the system clock, the same
discipline calculations/ enforces internally, applied one layer up, so it
stays deterministic and testable without patching a clock.
"""

from datetime import date

from apps.macro_note.calculations.changes import (
    Change,
    one_day_change,
    one_month_change,
    one_week_change,
)
from apps.macro_note.models import Metric, MetricChange, SeriesMeta
from apps.macro_note.store import ObservationStore

# Comfortably covers a 1-month change calculation with buffer for weekend/holiday gaps.
HISTORY_LOOKBACK = 45

# Tolerates a routine weekend (Fri->Mon is a 3-day gap) and a typical single-holiday
# long weekend (4-day gap) without flagging staleness; a 5+ day gap is a real outage.
STALE_THRESHOLD_DAYS = 4


def build_metric(
    series_meta: SeriesMeta, store: ObservationStore, note_date: date
) -> Metric | None:
    """Build today's Metric for one series, or None if the store has no data at all.

    Staleness rule: a Metric is stale if the most recent stored observation's
    as_of date is more than STALE_THRESHOLD_DAYS calendar days before note_date.
    This threshold absorbs routine weekend/holiday gaps (a Monday run legitimately
    reporting Friday's close is not stale) while still catching genuine source
    outages (day after day of no new data). The rule doesn't need to know WHY
    there's no fresh data for note_date -- a fetch that failed and a fetch that
    simply hasn't run yet look identical from the store's point of view, and
    are handled identically.
    """
    history = store.history(series_meta.series_id, lookback=HISTORY_LOOKBACK)
    if not history:
        return None

    latest = history[-1]
    gap_days = (note_date - latest.as_of).days
    stale = gap_days > STALE_THRESHOLD_DAYS

    return Metric(
        series_id=series_meta.series_id,
        label=series_meta.name,
        value=latest.value,
        unit=series_meta.unit,
        as_of=latest.as_of,
        change_1d=_to_metric_change(one_day_change(history)),
        change_1w=_to_metric_change(one_week_change(history)),
        change_1m=_to_metric_change(one_month_change(history)),
        stale=stale,
        stale_as_of=latest.as_of if stale else None,
    )


def _to_metric_change(change: Change) -> MetricChange:
    return MetricChange(
        pct_change=change.pct_change,
        bp_change=change.bp_change,
        reference_as_of=change.reference_as_of,
    )
