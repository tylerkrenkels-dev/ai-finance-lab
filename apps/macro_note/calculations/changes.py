"""Pure percentage and basis-point change calculations over an Observation history.

No I/O, no network, no clock reads. `history` is assumed sorted oldest-first,
matching store.history()'s contract -- these functions trust that ordering
rather than re-sorting defensively. The "current" point for every change is
always the last element of `history`, never a system clock read.
"""

import calendar
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

from apps.macro_note.models import Observation


class Change(BaseModel):
    """A percentage and basis-point change relative to a reference observation.

    None fields mean there wasn't enough history to compute the change --
    not zero, not an error.
    """

    model_config = ConfigDict(frozen=True)

    pct_change: float | None
    bp_change: float | None
    reference_as_of: date | None


def one_day_change(history: list[Observation]) -> Change:
    """Change from the most recent observation available on or before 1 calendar day ago."""
    return _change_since(history, days=1)


def one_week_change(history: list[Observation]) -> Change:
    """Change from the most recent observation available on or before 1 week ago."""
    return _change_since(history, days=7)


def one_month_change(history: list[Observation]) -> Change:
    """Change from the most recent observation available on or before 1 calendar month ago."""
    return _change_since(history, months=1)


_NO_CHANGE = Change(pct_change=None, bp_change=None, reference_as_of=None)


def _change_since(history: list[Observation], *, days: int = 0, months: int = 0) -> Change:
    if not history:
        return _NO_CHANGE

    latest = history[-1]
    target_date = (
        _months_before(latest.as_of, months) if months else latest.as_of - timedelta(days=days)
    )

    reference = _most_recent_on_or_before(history, target_date)
    if reference is None:
        return _NO_CHANGE

    bp_change = (latest.value - reference.value) * 100
    pct_change = (
        (latest.value - reference.value) / reference.value * 100 if reference.value != 0 else None
    )
    return Change(pct_change=pct_change, bp_change=bp_change, reference_as_of=reference.as_of)


def _most_recent_on_or_before(history: list[Observation], target_date: date) -> Observation | None:
    candidates = [obs for obs in history if obs.as_of <= target_date]
    return candidates[-1] if candidates else None


def _months_before(d: date, months: int) -> date:
    """Return the date `months` calendar months before `d`, clamping the day of month.

    E.g. 31-Mar minus 1 month -> 28-Feb (or 29-Feb in a leap year), not 3-Mar.
    """
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
