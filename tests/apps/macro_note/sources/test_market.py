from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from apps.macro_note.models import Observation
from apps.macro_note.sources.base import SourceProvider
from apps.macro_note.sources.market import MarketSource


def _history(rows: dict[str, list[object]], index: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=pd.to_datetime(index))


def _ticker_with_history(history: pd.DataFrame) -> MagicMock:
    ticker = MagicMock()
    ticker.history.return_value = history
    return ticker


def test_market_source_implements_source_provider() -> None:
    assert isinstance(MarketSource(), SourceProvider)


def test_fetch_observations_filters_nan_close() -> None:
    history = _history(
        {"Close": [1950.5, float("nan"), 1962.3]},
        ["2026-07-27", "2026-07-28", "2026-07-29"],
    )
    ticker = _ticker_with_history(history)
    source = MarketSource()

    with patch("yfinance.Ticker", return_value=ticker) as mock_ticker:
        observations = source.fetch_observations(
            series_id="gold",
            source_code="GC=F",
            start=date(2026, 7, 27),
            end=date(2026, 7, 29),
        )

    mock_ticker.assert_called_once_with("GC=F")
    assert len(observations) == 2
    assert all(isinstance(obs, Observation) for obs in observations)
    assert all(obs.series_id == "gold" for obs in observations)
    assert observations[0].value == 1950.5
    assert observations[0].as_of == date(2026, 7, 27)
    assert observations[1].value == 1962.3
    assert observations[1].as_of == date(2026, 7, 29)


def test_fetch_observations_returns_empty_for_empty_history_no_retry() -> None:
    ticker = _ticker_with_history(pd.DataFrame())
    source = MarketSource()

    with patch("yfinance.Ticker", return_value=ticker) as mock_ticker:
        observations = source.fetch_observations(
            series_id="asx200",
            source_code="^AXJO",
            start=date(2026, 7, 27),
            end=date(2026, 7, 29),
        )

    assert observations == []
    mock_ticker.assert_called_once()


def test_fetch_observations_retries_then_succeeds() -> None:
    history = _history({"Close": [10500.0]}, ["2026-07-27"])
    failing_ticker = MagicMock()
    failing_ticker.history.side_effect = ConnectionError("boom")
    succeeding_ticker = _ticker_with_history(history)
    source = MarketSource()

    with (
        patch("yfinance.Ticker", side_effect=[failing_ticker, succeeding_ticker]) as mock_ticker,
        patch("time.sleep") as mock_sleep,
    ):
        observations = source.fetch_observations(
            series_id="asx200",
            source_code="^AXJO",
            start=date(2026, 7, 27),
            end=date(2026, 7, 27),
        )

    assert mock_ticker.call_count == 2
    mock_sleep.assert_called_once()
    assert len(observations) == 1
    assert observations[0].value == 10500.0


def test_fetch_observations_never_raises_after_retries_exhausted() -> None:
    failing_ticker = MagicMock()
    failing_ticker.history.side_effect = ConnectionError("boom")
    source = MarketSource()

    with (
        patch("yfinance.Ticker", return_value=failing_ticker) as mock_ticker,
        patch("time.sleep") as mock_sleep,
    ):
        observations = source.fetch_observations(
            series_id="gold",
            source_code="GC=F",
            start=date(2026, 7, 27),
            end=date(2026, 7, 29),
        )

    assert observations == []
    assert mock_ticker.call_count == 4
    assert mock_sleep.call_count == 3


def test_fetch_observations_does_not_raise_pytest_fail() -> None:
    # Explicit sanity check that "never raises" holds even when the underlying
    # exception isn't a plain ConnectionError.
    failing_ticker = MagicMock()
    failing_ticker.history.side_effect = ValueError("Yahoo returned HTML, not JSON")
    source = MarketSource()

    with patch("yfinance.Ticker", return_value=failing_ticker), patch("time.sleep"):
        try:
            observations = source.fetch_observations(
                series_id="copper",
                source_code="HG=F",
                start=date(2026, 7, 27),
                end=date(2026, 7, 29),
            )
        except Exception as exc:  # pragma: no cover - failure path for this test itself
            pytest.fail(f"fetch_observations raised {exc!r}, it must never raise")

    assert observations == []
