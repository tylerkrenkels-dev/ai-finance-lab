"""Fundamentals connector: fetches a RawFundamentals snapshot per ticker from yfinance.

RawFundamentals is the layer boundary contract for this app: fetch_fundamentals()
builds one instance per ticker per call from yfinance's Ticker(ticker).info, and
everything downstream (calculations.py) consumes only this model, never the raw
dict. Investigated empirically against 5 real tickers (AAPL, MSFT, JPM, BHP.AX,
CBA.AX) before this was written -- three findings this model encodes:

1. Missing data has two real shapes -- key absent from .info entirely, or key
   present with a literal None (confirmed: CBA.AX's trailingPegRatio) -- and no
   downstream consumer needs to tell them apart, so every optional field on
   RawFundamentals collapses both into one None. Every field below is built with
   .get(field), never info[field].

2. currency and financial_currency can diverge for dual-listed names (BHP.AX:
   AUD price currency, USD financial-statement currency) -- both are carried as
   separate required fields, because any ratio mixing a price-derived field with
   a financials-derived field is only valid when they match.

3. Sector, not exchange, drives field patchiness -- financial-services tickers
   (JPM, CBA.AX) both lack enterprise_to_ebitda/ebitda/debt_to_equity/
   current_ratio/quick_ratio/free_cashflow regardless of market, while a
   same-exchange non-financial (BHP.AX) has every field. RawFundamentals does
   not classify which present values are sector-inapplicable (e.g.
   gross_margins=0.0 for a bank -- real, since a bank has no COGS, but not
   economically informative): that judgment is calculation logic and belongs in
   calculations.py, not here, by the same rule that keeps a connector from
   computing a percentage change. `sector` is always carried so that judgment is
   possible downstream without a second fetch.

Unlike apps.macro_note.sources.market.MarketSource's .history(timeout=...),
yfinance's .info/get_info() takes no timeout parameter anywhere in its public
API (Ticker(ticker, session=...) and get_info() were both checked directly --
neither accepts one). Reading yfinance's own data.py confirms it hardcodes
timeout=30 internally on every request, with no override. This connector can
therefore only bound total wait time via retries and backoff, not a per-call
timeout override -- the same "never raises, bounded attempts" resilience
contract as MarketSource, just without a timeout knob that doesn't exist.

No SourceProvider Protocol here, unlike apps.macro_note.sources: that
abstraction exists there because three real providers (FRED, RBA, yfinance)
implement it. This app has exactly one fundamentals source, so a class or
interface would have no second implementation to justify it -- a plain
function is the whole connector.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any, Literal

import yfinance
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 0.5


class RawFundamentals(BaseModel):
    """One ticker's raw fundamentals snapshot, fetched once from yfinance's .info."""

    ticker: str
    quote_type: Literal["EQUITY"]
    company_name: str
    sector: str | None
    currency: str
    financial_currency: str

    market_cap: int | None
    enterprise_value: int | None

    trailing_pe: float | None
    forward_pe: float | None
    price_to_book: float | None
    price_to_sales_ttm: float | None
    enterprise_to_ebitda: float | None
    enterprise_to_revenue: float | None

    trailing_eps: float | None
    forward_eps: float | None
    total_revenue: int | None
    ebitda: int | None

    gross_margins: float | None
    operating_margins: float | None
    profit_margins: float | None
    return_on_equity: float | None
    return_on_assets: float | None

    debt_to_equity: float | None
    current_ratio: float | None
    quick_ratio: float | None

    dividend_yield: float | None = Field(
        default=None,
        description=(
            "Already expressed as a percent, not a fraction -- confirmed empirically: "
            "AAPL's dividend_yield=0.35 means 0.35%, matching its real ~0.35% yield. "
            "This is the OPPOSITE convention from every margin/return field on this "
            "model (gross_margins, operating_margins, profit_margins, return_on_equity, "
            "return_on_assets), which are fractions (profit_margins=0.276 means 27.6%). "
            "Formatting every ratio field the same way is correct for those and "
            "silently 100x wrong for this one."
        ),
    )

    beta: float | None
    current_price: float
    previous_close: float | None
    fifty_two_week_high: float | None
    fifty_two_week_low: float | None

    free_cashflow: int | None
    operating_cashflow: int | None
    shares_outstanding: int | None

    quote_as_of: datetime
    fetched_at: datetime


def fetch_fundamentals(ticker: str) -> RawFundamentals | None:
    """Fetch one ticker's RawFundamentals snapshot from yfinance.

    Never raises: any failure (yfinance unreachable, or a response that fails
    RawFundamentals's validation -- e.g. no current_price, or a quote_type other
    than "EQUITY") is logged and reported as None, so the caller can fall back to
    the last stored value and mark the metric stale by date, the same resilience
    contract as apps.macro_note.sources.market.MarketSource.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            return _fetch(ticker)
        except Exception as exc:  # yfinance's failures aren't enumerable enough to whitelist
            logger.warning(
                "yfinance fundamentals fetch failed for %s (attempt %d/%d): %s",
                ticker,
                attempt + 1,
                MAX_RETRIES + 1,
                exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE_SECONDS * (2**attempt))

    logger.error(
        "yfinance fundamentals unavailable for %s after %d attempts; treating as no data",
        ticker,
        MAX_RETRIES + 1,
    )
    return None


def _fetch(ticker: str) -> RawFundamentals:
    info: Any = yfinance.Ticker(ticker).info
    fetched_at = datetime.now(UTC)
    return RawFundamentals(
        ticker=ticker,
        quote_type=info.get("quoteType"),
        company_name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"),
        currency=info.get("currency"),
        financial_currency=info.get("financialCurrency"),
        market_cap=info.get("marketCap"),
        enterprise_value=info.get("enterpriseValue"),
        trailing_pe=info.get("trailingPE"),
        forward_pe=info.get("forwardPE"),
        price_to_book=info.get("priceToBook"),
        price_to_sales_ttm=info.get("priceToSalesTrailing12Months"),
        enterprise_to_ebitda=info.get("enterpriseToEbitda"),
        enterprise_to_revenue=info.get("enterpriseToRevenue"),
        trailing_eps=info.get("trailingEps"),
        forward_eps=info.get("forwardEps"),
        total_revenue=info.get("totalRevenue"),
        ebitda=info.get("ebitda"),
        gross_margins=info.get("grossMargins"),
        operating_margins=info.get("operatingMargins"),
        profit_margins=info.get("profitMargins"),
        return_on_equity=info.get("returnOnEquity"),
        return_on_assets=info.get("returnOnAssets"),
        debt_to_equity=info.get("debtToEquity"),
        current_ratio=info.get("currentRatio"),
        quick_ratio=info.get("quickRatio"),
        dividend_yield=info.get("dividendYield"),
        beta=info.get("beta"),
        current_price=info.get("currentPrice") or info.get("regularMarketPrice"),
        previous_close=info.get("previousClose"),
        fifty_two_week_high=info.get("fiftyTwoWeekHigh"),
        fifty_two_week_low=info.get("fiftyTwoWeekLow"),
        free_cashflow=info.get("freeCashflow"),
        operating_cashflow=info.get("operatingCashflow"),
        shares_outstanding=info.get("sharesOutstanding"),
        quote_as_of=datetime.fromtimestamp(info.get("regularMarketTime"), tz=UTC),
        fetched_at=fetched_at,
    )
