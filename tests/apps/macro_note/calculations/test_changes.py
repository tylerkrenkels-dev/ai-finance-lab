from collections.abc import Callable
from datetime import UTC, date, datetime

import pytest

from apps.macro_note.calculations.changes import (
    Change,
    one_day_change,
    one_month_change,
    one_week_change,
)
from apps.macro_note.models import Observation


def _obs(as_of: date, value: float) -> Observation:
    return Observation(series_id="us_10y", value=value, as_of=as_of, fetched_at=datetime.now(UTC))


# Oldest-first, matching store.history()'s contract. Latest is 2026-07-20 (Mon).
HISTORY = [
    _obs(date(2026, 6, 19), 4.00),  # Fri
    _obs(date(2026, 7, 13), 4.10),  # Mon
    _obs(date(2026, 7, 14), 4.12),  # Tue
    _obs(date(2026, 7, 15), 4.15),  # Wed
    _obs(date(2026, 7, 16), 4.18),  # Thu
    _obs(date(2026, 7, 17), 4.20),  # Fri
    _obs(date(2026, 7, 20), 4.25),  # Mon, latest
]


def test_one_day_change_falls_back_to_last_trading_day() -> None:
    # target = 2026-07-19 (Sun), no data -> falls back to 2026-07-17 (Fri)
    result = one_day_change(HISTORY)

    assert result.pct_change == pytest.approx(1.190476, rel=1e-6)
    assert result.bp_change == pytest.approx(5.0)
    assert result.reference_as_of == date(2026, 7, 17)


def test_one_week_change_exact_match() -> None:
    # target = 2026-07-13, exact match
    result = one_week_change(HISTORY)

    assert result.pct_change == pytest.approx(3.658536, rel=1e-6)
    assert result.bp_change == pytest.approx(15.0)
    assert result.reference_as_of == date(2026, 7, 13)


def test_one_month_change_falls_back_across_month_boundary() -> None:
    # target = months_before(2026-07-20, 1) = 2026-06-20, no data -> falls back to 2026-06-19 (Fri)
    result = one_month_change(HISTORY)

    assert result.pct_change == pytest.approx(6.25, rel=1e-6)
    assert result.bp_change == pytest.approx(25.0)
    assert result.reference_as_of == date(2026, 6, 19)


@pytest.mark.parametrize("change_fn", [one_day_change, one_week_change, one_month_change])
def test_not_enough_history_returns_all_none(
    change_fn: Callable[[list[Observation]], Change],
) -> None:
    single = [_obs(date(2026, 7, 20), 4.25)]

    result = change_fn(single)

    assert result.pct_change is None
    assert result.bp_change is None
    assert result.reference_as_of is None


def test_empty_history_returns_all_none() -> None:
    result = one_day_change([])

    assert result.pct_change is None
    assert result.bp_change is None
    assert result.reference_as_of is None


def test_zero_value_reference_guards_percentage_but_not_basis_points() -> None:
    zero_ref_history = [
        _obs(date(2026, 1, 1), 0.00),
        _obs(date(2026, 1, 2), 0.10),
    ]

    result = one_day_change(zero_ref_history)

    assert result.pct_change is None
    assert result.bp_change == pytest.approx(10.0)
    assert result.reference_as_of == date(2026, 1, 1)
