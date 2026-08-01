from datetime import UTC, date, datetime

import pytest

from apps.macro_note.calculations.rates import (
    au_3s10s_slope,
    au_us_10y_spread,
    us_2s10s_slope,
)
from apps.macro_note.models import Observation


def _obs(series_id: str, as_of: date, value: float) -> Observation:
    return Observation(series_id=series_id, value=value, as_of=as_of, fetched_at=datetime.now(UTC))


US_2Y = _obs("us_2y", date(2026, 7, 20), 3.85)
US_10Y = _obs("us_10y", date(2026, 7, 20), 4.25)
AU_3Y = _obs("au_3y", date(2026, 7, 20), 3.60)
AU_10Y = _obs("au_10y", date(2026, 7, 20), 4.10)
AU_10Y_EARLIER = _obs("au_10y", date(2026, 7, 18), 4.10)


def test_us_2s10s_slope() -> None:
    result = us_2s10s_slope(US_2Y, US_10Y)

    assert result.spread_bp == pytest.approx(40.0)
    assert result.first_as_of == date(2026, 7, 20)
    assert result.second_as_of == date(2026, 7, 20)


def test_au_3s10s_slope() -> None:
    result = au_3s10s_slope(AU_3Y, AU_10Y)

    assert result.spread_bp == pytest.approx(50.0)
    assert result.first_as_of == date(2026, 7, 20)
    assert result.second_as_of == date(2026, 7, 20)


def test_au_us_10y_spread() -> None:
    result = au_us_10y_spread(US_10Y, AU_10Y)

    assert result.spread_bp == pytest.approx(-15.0)
    assert result.first_as_of == date(2026, 7, 20)
    assert result.second_as_of == date(2026, 7, 20)


def test_au_us_10y_spread_computes_despite_mismatched_dates() -> None:
    result = au_us_10y_spread(US_10Y, AU_10Y_EARLIER)

    assert result.spread_bp == pytest.approx(-15.0)
    assert result.first_as_of == date(2026, 7, 20)
    assert result.second_as_of == date(2026, 7, 18)


def test_au_us_10y_spread_missing_leg_returns_symmetric_none() -> None:
    result = au_us_10y_spread(None, AU_10Y)

    assert result.spread_bp is None
    assert result.first_as_of is None
    assert result.second_as_of is None
