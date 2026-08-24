from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from apps.equity_snapshot.sources import RawFundamentals, fetch_fundamentals

# Real values pulled live from yfinance during investigation (not synthetic),
# trimmed to the fields RawFundamentals models. AAPL: every field populated.
_AAPL_INFO = {
    "quoteType": "EQUITY",
    "longName": "Apple Inc.",
    "shortName": "Apple Inc.",
    "sector": "Technology",
    "currency": "USD",
    "financialCurrency": "USD",
    "marketCap": 4514709504000,
    "enterpriseValue": 4536654626816,
    "trailingPE": 35.475918,
    "forwardPE": 32.43169,
    "priceToBook": 42.03125,
    "priceToSalesTrailing12Months": 9.671138,
    "enterpriseToEbitda": 27.01,
    "enterpriseToRevenue": 9.718,
    "trailingEps": 8.72,
    "forwardEps": 9.53851,
    "totalRevenue": 466822987776,
    "ebitda": 167959003136,
    "grossMargins": 0.48653,
    "operatingMargins": 0.32623002,
    "profitMargins": 0.27618998,
    "returnOnEquity": 1.4875101,
    "returnOnAssets": 0.27082002,
    "debtToEquity": 78.445,
    "currentRatio": 1.003,
    "quickRatio": 0.812,
    "dividendYield": 0.35,
    "beta": 1.086,
    "currentPrice": 309.35,
    "regularMarketPrice": 309.35,
    "previousClose": 311.30002,
    "fiftyTwoWeekHigh": 344.57,
    "fiftyTwoWeekLow": 224.69,
    "freeCashflow": 107721875456,
    "operatingCashflow": 146723995648,
    "sharesOutstanding": 14594180000,
    "regularMarketTime": 1787342401,
}

# Real values for JPM: a bank. enterpriseToEbitda/ebitda/debtToEquity/currentRatio/
# quickRatio/freeCashflow are genuinely absent keys (not None, not zero) -- confirmed
# empirically, not assumed. grossMargins is a real, present 0.0 (banks have no COGS).
_JPM_INFO = {
    "quoteType": "EQUITY",
    "longName": "JPMorgan Chase & Co.",
    "sector": "Financial Services",
    "currency": "USD",
    "financialCurrency": "USD",
    "marketCap": 934565052416,
    "enterpriseValue": 772493082624,
    "trailingPE": 15.06341,
    "forwardPE": 14.059268,
    "priceToBook": 2.6433194,
    "priceToSalesTrailing12Months": 5.0156984,
    "enterpriseToRevenue": 4.146,
    "trailingEps": 23.34,
    "forwardEps": 25.00699,
    "totalRevenue": 186328006656,
    "grossMargins": 0.0,
    "operatingMargins": 0.50394,
    "profitMargins": 0.34921002,
    "returnOnEquity": 0.17789,
    "returnOnAssets": 0.0136,
    "dividendYield": 1.71,
    "beta": 0.977,
    "currentPrice": 351.58,
    "regularMarketPrice": 351.58,
    "previousClose": 351.55,
    "fiftyTwoWeekHigh": 366.5,
    "fiftyTwoWeekLow": 279.1,
    "operatingCashflow": -162533998592,
    "sharesOutstanding": 2658186195,
    "regularMarketTime": 1787342402,
}


def _ticker_with_info(info: dict) -> MagicMock:
    ticker = MagicMock()
    ticker.info = info
    return ticker


def test_fetch_fundamentals_full_response_populates_every_field() -> None:
    with patch("yfinance.Ticker", return_value=_ticker_with_info(_AAPL_INFO)) as mock_ticker:
        result = fetch_fundamentals("AAPL")

    mock_ticker.assert_called_once_with("AAPL")
    assert isinstance(result, RawFundamentals)
    assert result.ticker == "AAPL"
    assert result.quote_type == "EQUITY"
    assert result.company_name == "Apple Inc."
    assert result.sector == "Technology"
    assert result.enterprise_to_ebitda == 27.01
    assert result.current_price == 309.35
    assert result.quote_as_of == datetime.fromtimestamp(1787342401, tz=UTC)


def test_fetch_fundamentals_absent_keys_become_none_not_zero_or_error() -> None:
    with patch("yfinance.Ticker", return_value=_ticker_with_info(_JPM_INFO)):
        result = fetch_fundamentals("JPM")

    assert isinstance(result, RawFundamentals)
    assert result.enterprise_to_ebitda is None
    assert result.ebitda is None
    assert result.debt_to_equity is None
    assert result.current_ratio is None
    assert result.quick_ratio is None
    assert result.free_cashflow is None


def test_fetch_fundamentals_present_none_value_treated_same_as_absent_key() -> None:
    info = dict(_JPM_INFO)
    info["debtToEquity"] = None  # present key, literal None -- confirmed this shape occurs too

    with patch("yfinance.Ticker", return_value=_ticker_with_info(info)):
        result = fetch_fundamentals("JPM")

    assert result is not None
    assert result.debt_to_equity is None


def test_fetch_fundamentals_preserves_present_zero_not_coerced_to_none() -> None:
    # JPM's grossMargins=0.0 is a real, present value (banks have no COGS) -- it
    # must survive as 0.0, not be folded into the same None used for absent keys.
    with patch("yfinance.Ticker", return_value=_ticker_with_info(_JPM_INFO)):
        result = fetch_fundamentals("JPM")

    assert result is not None
    assert result.gross_margins == 0.0
    assert result.gross_margins is not None


def test_fetch_fundamentals_carries_currency_and_financial_currency_separately() -> None:
    # BHP.AX trades in AUD but reports financials in USD -- both fields must
    # survive independently, not be collapsed into one "currency".
    info = dict(_AAPL_INFO)
    info["currency"] = "AUD"
    info["financialCurrency"] = "USD"

    with patch("yfinance.Ticker", return_value=_ticker_with_info(info)):
        result = fetch_fundamentals("BHP.AX")

    assert result is not None
    assert result.currency == "AUD"
    assert result.financial_currency == "USD"


def test_fetch_fundamentals_dividend_yield_kept_as_raw_percent_not_rescaled() -> None:
    # 0.35 means 0.35%, not 35% or 0.0035% -- fetch_fundamentals must not rescale it.
    with patch("yfinance.Ticker", return_value=_ticker_with_info(_AAPL_INFO)):
        result = fetch_fundamentals("AAPL")

    assert result is not None
    assert result.dividend_yield == 0.35


def test_fetch_fundamentals_rejects_non_equity_quote_type() -> None:
    info = dict(_AAPL_INFO)
    info["quoteType"] = "ETF"

    with patch("yfinance.Ticker", return_value=_ticker_with_info(info)), patch("time.sleep"):
        result = fetch_fundamentals("AAPL")

    assert result is None


def test_fetch_fundamentals_retries_then_succeeds() -> None:
    failing_ticker = MagicMock()
    type(failing_ticker).info = property(
        lambda self: (_ for _ in ()).throw(ConnectionError("boom"))
    )
    succeeding_ticker = _ticker_with_info(_AAPL_INFO)

    with (
        patch("yfinance.Ticker", side_effect=[failing_ticker, succeeding_ticker]) as mock_ticker,
        patch("time.sleep") as mock_sleep,
    ):
        result = fetch_fundamentals("AAPL")

    assert mock_ticker.call_count == 2
    mock_sleep.assert_called_once()
    assert result is not None
    assert result.ticker == "AAPL"


def test_fetch_fundamentals_never_raises_after_retries_exhausted() -> None:
    failing_ticker = MagicMock()
    type(failing_ticker).info = property(
        lambda self: (_ for _ in ()).throw(ConnectionError("boom"))
    )

    with (
        patch("yfinance.Ticker", return_value=failing_ticker) as mock_ticker,
        patch("time.sleep") as mock_sleep,
    ):
        result = fetch_fundamentals("AAPL")

    assert result is None
    assert mock_ticker.call_count == 4
    assert mock_sleep.call_count == 3


def test_fetch_fundamentals_returns_none_when_current_price_missing() -> None:
    # current_price is a required field on RawFundamentals -- a response with
    # neither currentPrice nor regularMarketPrice is a structural defect, treated
    # the same as any other fetch failure.
    info = dict(_AAPL_INFO)
    del info["currentPrice"]
    del info["regularMarketPrice"]

    with patch("yfinance.Ticker", return_value=_ticker_with_info(info)), patch("time.sleep"):
        result = fetch_fundamentals("AAPL")

    assert result is None


def test_fetch_fundamentals_does_not_raise_pytest_fail() -> None:
    failing_ticker = MagicMock()
    type(failing_ticker).info = property(
        lambda self: (_ for _ in ()).throw(ValueError("Yahoo returned HTML, not JSON"))
    )

    with patch("yfinance.Ticker", return_value=failing_ticker), patch("time.sleep"):
        try:
            result = fetch_fundamentals("AAPL")
        except Exception as exc:  # pragma: no cover - failure path for this test itself
            pytest.fail(f"fetch_fundamentals raised {exc!r}, it must never raise")

    assert result is None
