from datetime import UTC, date, datetime

import pytest

from apps.macro_note.calculations.fx import one_day_carry, one_month_carry, one_week_carry
from apps.macro_note.models import Observation


def _obs(series_id: str, as_of: date, value: float) -> Observation:
    return Observation(series_id=series_id, value=value, as_of=as_of, fetched_at=datetime.now(UTC))


AU_CASH_RATE = _obs("au_cash_rate", date(2026, 7, 20), 4.35)
US_FED_FUNDS = _obs("us_fed_funds", date(2026, 7, 20), 4.50)

# Given dataset: only 2 points, deliberately sparse, used for the 1-month case.
MONTH_HISTORY = [
    _obs("aud_usd", date(2026, 6, 19), 0.6500),  # Fri
    _obs("aud_usd", date(2026, 7, 20), 0.6630),  # Mon, latest
]

# Constructed for 1-day/1-week: a denser week of daily AUD/USD prints, same
# dates as changes.py's own test series, spanning one weekend gap.
WEEK_HISTORY = [
    _obs("aud_usd", date(2026, 7, 13), 0.6550),  # Mon
    _obs("aud_usd", date(2026, 7, 14), 0.6560),  # Tue
    _obs("aud_usd", date(2026, 7, 15), 0.6580),  # Wed
    _obs("aud_usd", date(2026, 7, 16), 0.6600),  # Thu
    _obs("aud_usd", date(2026, 7, 17), 0.6610),  # Fri
    _obs("aud_usd", date(2026, 7, 20), 0.6630),  # Mon, latest
]


def test_one_month_carry_falls_back_across_month_boundary() -> None:
    # target = months_before(2026-07-20, 1) = 2026-06-20, no data -> falls back to 2026-06-19
    result = one_month_carry(AU_CASH_RATE, US_FED_FUNDS, MONTH_HISTORY)

    assert result.rate_differential_pct == pytest.approx(-0.15)
    assert result.window_days == 31
    assert result.annualised_spot_change_pct == pytest.approx(23.548387, rel=1e-6)
    assert result.annualised_return_pct == pytest.approx(23.398387, rel=1e-6)


def test_one_day_carry_falls_back_to_last_trading_day() -> None:
    # target = 2026-07-19 (Sun), no data -> falls back to 2026-07-17 (Fri)
    result = one_day_carry(AU_CASH_RATE, US_FED_FUNDS, WEEK_HISTORY)

    assert result.rate_differential_pct == pytest.approx(-0.15)
    assert result.window_days == 3
    assert result.annualised_spot_change_pct == pytest.approx(36.812910, rel=1e-6)
    assert result.annualised_return_pct == pytest.approx(36.662910, rel=1e-6)


def test_one_week_carry_exact_match() -> None:
    # target = 2026-07-13, exact match
    result = one_week_carry(AU_CASH_RATE, US_FED_FUNDS, WEEK_HISTORY)

    assert result.rate_differential_pct == pytest.approx(-0.15)
    assert result.window_days == 7
    assert result.annualised_spot_change_pct == pytest.approx(63.685932, rel=1e-6)
    assert result.annualised_return_pct == pytest.approx(63.535932, rel=1e-6)


def test_missing_rate_leg_leaves_spot_component_populated() -> None:
    result = one_month_carry(None, US_FED_FUNDS, MONTH_HISTORY)

    assert result.rate_differential_pct is None
    assert result.annualised_return_pct is None
    assert result.window_days == 31
    assert result.annualised_spot_change_pct == pytest.approx(23.548387, rel=1e-6)


def test_insufficient_fx_history_leaves_rate_differential_populated() -> None:
    # A single observation exists, but there's no earlier point to use as a reference --
    # a distinct code path from an empty history entirely.
    single_observation = [_obs("aud_usd", date(2026, 7, 20), 0.6630)]

    result = one_month_carry(AU_CASH_RATE, US_FED_FUNDS, single_observation)

    assert result.annualised_spot_change_pct is None
    assert result.window_days is None
    assert result.annualised_return_pct is None
    assert result.rate_differential_pct == pytest.approx(-0.15)


def test_missing_fx_history_leaves_rate_differential_populated() -> None:
    result = one_month_carry(AU_CASH_RATE, US_FED_FUNDS, [])

    assert result.annualised_spot_change_pct is None
    assert result.window_days is None
    assert result.annualised_return_pct is None
    assert result.rate_differential_pct == pytest.approx(-0.15)


def test_both_missing_returns_all_none() -> None:
    result = one_month_carry(None, None, [])

    assert result.rate_differential_pct is None
    assert result.annualised_spot_change_pct is None
    assert result.window_days is None
    assert result.annualised_return_pct is None
