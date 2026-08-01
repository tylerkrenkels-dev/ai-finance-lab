"""AUD/USD policy-rate carry calculation.

Ex-post realized decomposition of the AUD/USD carry trade return into a
rate-differential component and an annualised spot-move component. This is
NOT an ex-ante UIP forecast -- it does not use forward rates or claim to
predict future spot moves; it decomposes what already happened into its
two additive pieces, per the standard linearized UIP carry-return identity.

No I/O, no network. Reuses changes.py's on-or-before search (via
one_day_change / one_week_change / one_month_change) for the spot-move
component rather than reimplementing it.
"""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from apps.macro_note.calculations.changes import (
    Change,
    one_day_change,
    one_month_change,
    one_week_change,
)
from apps.macro_note.models import Observation

DAYS_PER_YEAR = 365

_SpotChangeFn = Callable[[list[Observation]], Change]


class Carry(BaseModel):
    """Ex-post AUD/USD carry: rate differential + annualised spot move.

    Each sub-component is populated independently of the other -- a
    deliberate departure from Change/Spread's all-or-nothing pattern,
    since Carry decomposes two genuinely independent building blocks.
    annualised_return_pct is populated only when both sub-components are.
    None fields mean that particular piece couldn't be computed -- not
    zero, not an error.
    """

    model_config = ConfigDict(frozen=True)

    annualised_return_pct: float | None
    rate_differential_pct: float | None
    annualised_spot_change_pct: float | None
    window_days: int | None


def one_day_carry(
    au_cash_rate: Observation | None,
    us_fed_funds: Observation | None,
    aud_usd_history: list[Observation],
) -> Carry:
    """AUD/USD carry using the 1-day spot move (see changes.one_day_change)."""
    return _carry(au_cash_rate, us_fed_funds, aud_usd_history, one_day_change)


def one_week_carry(
    au_cash_rate: Observation | None,
    us_fed_funds: Observation | None,
    aud_usd_history: list[Observation],
) -> Carry:
    """AUD/USD carry using the 1-week spot move (see changes.one_week_change)."""
    return _carry(au_cash_rate, us_fed_funds, aud_usd_history, one_week_change)


def one_month_carry(
    au_cash_rate: Observation | None,
    us_fed_funds: Observation | None,
    aud_usd_history: list[Observation],
) -> Carry:
    """AUD/USD carry using the 1-month spot move (see changes.one_month_change)."""
    return _carry(au_cash_rate, us_fed_funds, aud_usd_history, one_month_change)


def _carry(
    au_cash_rate: Observation | None,
    us_fed_funds: Observation | None,
    aud_usd_history: list[Observation],
    spot_change_fn: _SpotChangeFn,
) -> Carry:
    rate_differential_pct = (
        au_cash_rate.value - us_fed_funds.value
        if au_cash_rate is not None and us_fed_funds is not None
        else None
    )

    annualised_spot_change_pct, window_days = _annualised_spot_change(
        aud_usd_history, spot_change_fn
    )

    annualised_return_pct = (
        rate_differential_pct + annualised_spot_change_pct
        if rate_differential_pct is not None and annualised_spot_change_pct is not None
        else None
    )

    return Carry(
        annualised_return_pct=annualised_return_pct,
        rate_differential_pct=rate_differential_pct,
        annualised_spot_change_pct=annualised_spot_change_pct,
        window_days=window_days,
    )


def _annualised_spot_change(
    aud_usd_history: list[Observation], spot_change_fn: _SpotChangeFn
) -> tuple[float | None, int | None]:
    if not aud_usd_history:
        return None, None

    spot_change = spot_change_fn(aud_usd_history)
    if spot_change.pct_change is None or spot_change.reference_as_of is None:
        return None, None

    latest = aud_usd_history[-1]
    window_days = (latest.as_of - spot_change.reference_as_of).days
    if window_days <= 0:
        return None, None

    return spot_change.pct_change * (DAYS_PER_YEAR / window_days), window_days
