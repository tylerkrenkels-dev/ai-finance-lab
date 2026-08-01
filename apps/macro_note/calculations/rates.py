"""Pure basis-point spread/curve-slope calculations between two point-in-time Observations.

No I/O, no network. Unlike changes.py, these are cross-sectional (two series,
roughly the same date), not longitudinal (one series, two dates), so there's
no history or lookback to search -- the caller already knows which two
Observations it wants compared, e.g. from store.latest(series_id).
"""

from datetime import date

from pydantic import BaseModel, ConfigDict

from apps.macro_note.models import Observation


class Spread(BaseModel):
    """A basis-point difference between two point-in-time Observations.

    spread_bp = second.value - first.value, scaled by 100 -- values are
    percentage-point-scaled (e.g. 4.25 meaning 4.25%), same convention as
    changes.py: 1 percentage point = 100 basis points.

    None fields mean one or both legs were unavailable -- not zero, not
    an error. first_as_of and second_as_of are not required to match: AU
    and US trading calendars genuinely differ, so a small gap between the
    two dates is expected, not a bug. Deciding whether a gap is too large
    to trust is left to whatever calls this, not this pure function.
    """

    model_config = ConfigDict(frozen=True)

    spread_bp: float | None
    first_as_of: date | None
    second_as_of: date | None


_NO_SPREAD = Spread(spread_bp=None, first_as_of=None, second_as_of=None)


def us_2s10s_slope(us_2y: Observation | None, us_10y: Observation | None) -> Spread:
    """US 10y minus 2y, in basis points. Negative means an inverted curve."""
    return _spread(us_2y, us_10y)


def au_3s10s_slope(au_3y: Observation | None, au_10y: Observation | None) -> Spread:
    """AU 10y minus 3y, in basis points. Negative means an inverted curve.

    Named 3s10s, not 2s10s: the registry has no AU 2-year series (only
    cash rate, and 3y/10y government bond yields), so this is the closest
    AU curve-slope analogue actually computable from stored data.
    """
    return _spread(au_3y, au_10y)


def au_us_10y_spread(us_10y: Observation | None, au_10y: Observation | None) -> Spread:
    """AU 10y minus US 10y, in basis points. Positive means AU yields trade over US."""
    return _spread(us_10y, au_10y)


def _spread(first: Observation | None, second: Observation | None) -> Spread:
    if first is None or second is None:
        return _NO_SPREAD
    return Spread(
        spread_bp=(second.value - first.value) * 100,
        first_as_of=first.as_of,
        second_as_of=second.as_of,
    )
