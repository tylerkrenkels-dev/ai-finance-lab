from datetime import UTC, datetime

from apps.equity_snapshot.calculations import (
    FINANCIAL_SERVICES_SECTOR,
    ProfitabilityMetrics,
    ValuationMultiples,
    profitability_metrics,
    valuation_multiples,
)
from apps.equity_snapshot.sources import RawFundamentals

_FETCHED_AT = datetime(2026, 8, 24, 1, 19, 11, tzinfo=UTC)

# Real values pulled live from yfinance during investigation, at full raw precision
# (not the 3dp-rounded display table shown mid-conversation -- that table was for
# readability only, and using it as a data source would mean testing against inputs
# yfinance never actually returns).
_AAPL = RawFundamentals(
    ticker="AAPL",
    quote_type="EQUITY",
    company_name="Apple Inc.",
    sector="Technology",
    currency="USD",
    financial_currency="USD",
    market_cap=4514709504000,
    enterprise_value=4536654626816,
    trailing_pe=35.475918,
    forward_pe=32.43169,
    price_to_book=42.03125,
    price_to_sales_ttm=9.671138,
    enterprise_to_ebitda=27.01,
    enterprise_to_revenue=9.718,
    trailing_eps=8.72,
    forward_eps=9.53851,
    total_revenue=466822987776,
    ebitda=167959003136,
    gross_margins=0.48653,
    operating_margins=0.32623002,
    profit_margins=0.27618998,
    return_on_equity=1.4875101,
    return_on_assets=0.27082002,
    debt_to_equity=78.445,
    current_ratio=1.003,
    quick_ratio=0.812,
    dividend_yield=0.35,
    beta=1.086,
    current_price=309.35,
    previous_close=311.30002,
    fifty_two_week_high=344.57,
    fifty_two_week_low=224.69,
    free_cashflow=107721875456,
    operating_cashflow=146723995648,
    shares_outstanding=14594180000,
    quote_as_of=datetime.fromtimestamp(1787342401, tz=UTC),
    fetched_at=_FETCHED_AT,
)

# JPM: a bank. enterprise_to_ebitda/ebitda/debt_to_equity/current_ratio/quick_ratio/
# free_cashflow are genuinely absent from the raw fetch (None), not a currency-gate
# outcome -- currency == financial_currency (USD/USD) here.
_JPM = RawFundamentals(
    ticker="JPM",
    quote_type="EQUITY",
    company_name="JPMorgan Chase & Co.",
    sector="Financial Services",
    currency="USD",
    financial_currency="USD",
    market_cap=934565052416,
    enterprise_value=772493082624,
    trailing_pe=15.06341,
    forward_pe=14.059268,
    price_to_book=2.6433194,
    price_to_sales_ttm=5.0156984,
    enterprise_to_ebitda=None,
    enterprise_to_revenue=4.146,
    trailing_eps=23.34,
    forward_eps=25.00699,
    total_revenue=186328006656,
    ebitda=None,
    gross_margins=0.0,
    operating_margins=0.50394,
    profit_margins=0.34921002,
    return_on_equity=0.17789,
    return_on_assets=0.0136,
    debt_to_equity=None,
    current_ratio=None,
    quick_ratio=None,
    dividend_yield=1.71,
    beta=0.977,
    current_price=351.58,
    previous_close=351.55,
    fifty_two_week_high=366.5,
    fifty_two_week_low=279.1,
    free_cashflow=None,
    operating_cashflow=-162533998592,
    shares_outstanding=2658186195,
    quote_as_of=datetime.fromtimestamp(1787342402, tz=UTC),
    fetched_at=_FETCHED_AT,
)

# BHP.AX: currency="AUD" but financial_currency="USD" -- a real, present
# enterprise_to_ebitda (11.58) exists in the raw fetch, so its None in the
# calculated output must come from the currency gate, not from absence.
_BHP = RawFundamentals(
    ticker="BHP.AX",
    quote_type="EQUITY",
    company_name="BHP Group Limited",
    sector="Basic Materials",
    currency="AUD",
    financial_currency="USD",
    market_cap=340878950400,
    enterprise_value=346287439872,
    trailing_pe=24.760147,
    forward_pe=18.619112,
    price_to_book=4.765077,
    price_to_sales_ttm=5.8012075,
    enterprise_to_ebitda=11.58,
    enterprise_to_revenue=5.893,
    trailing_eps=2.71,
    forward_eps=3.627871,
    total_revenue=58759999488,
    ebitda=29902999552,
    gross_margins=0.85920995,
    operating_margins=0.4334,
    profit_margins=0.16734,
    return_on_equity=0.24002,
    return_on_assets=0.13434,
    debt_to_equity=50.473,
    current_ratio=1.885,
    quick_ratio=1.434,
    dividend_yield=3.73,
    beta=0.842,
    current_price=67.1,
    previous_close=65.16,
    fifty_two_week_high=67.72,
    fifty_two_week_low=39.3,
    free_cashflow=9592375296,
    operating_cashflow=21777999872,
    shares_outstanding=5080163098,
    quote_as_of=datetime.fromtimestamp(1787532562, tz=UTC),
    fetched_at=_FETCHED_AT,
)

# CBA.AX: a bank, like JPM, so enterprise_to_ebitda/ebitda are genuinely absent --
# but unlike BHP.AX, currency == financial_currency (AUD/AUD) here. Its
# enterprise_to_ebitda=None therefore comes from the same "absent from raw data"
# path as JPM's, not the currency gate BHP.AX goes through, even though both
# tickers are ASX-listed.
_CBA = RawFundamentals(
    ticker="CBA.AX",
    quote_type="EQUITY",
    company_name="Commonwealth Bank of Australia",
    sector="Financial Services",
    currency="AUD",
    financial_currency="AUD",
    market_cap=259777396736,
    enterprise_value=397637517312,
    trailing_pe=23.868662,
    forward_pe=22.909895,
    price_to_book=3.3006563,
    price_to_sales_ttm=8.848048,
    enterprise_to_ebitda=None,
    enterprise_to_revenue=13.541,
    trailing_eps=6.51,
    forward_eps=6.78244,
    total_revenue=29365000192,
    ebitda=None,
    gross_margins=0.0,
    operating_margins=0.56197,
    profit_margins=0.37003,
    return_on_equity=0.13857001,
    return_on_assets=0.00778,
    debt_to_equity=None,
    current_ratio=None,
    quick_ratio=None,
    dividend_yield=3.2,
    beta=0.81,
    current_price=155.385,
    previous_close=157.99,
    fifty_two_week_high=185.59,
    fifty_two_week_low=146.98,
    free_cashflow=None,
    operating_cashflow=-86123003904,
    shares_outstanding=1671830607,
    quote_as_of=datetime.fromtimestamp(1787532561, tz=UTC),
    fetched_at=_FETCHED_AT,
)


def test_valuation_multiples_aapl_full_precision() -> None:
    result = valuation_multiples(_AAPL)

    assert result == ValuationMultiples(
        trailing_pe=35.48, forward_pe=32.43, enterprise_to_ebitda=27.01
    )


def test_profitability_metrics_aapl_full_precision() -> None:
    result = profitability_metrics(_AAPL)

    assert result == ProfitabilityMetrics(
        gross_margin_pct=48.65,
        operating_margin_pct=32.62,
        profit_margin_pct=27.62,
        return_on_equity_pct=148.75,
    )


def test_profitability_metrics_aapl_roe_above_100_percent_not_clamped() -> None:
    # 1.4875101 is a real ROE > 100% (buybacks can push equity low enough for
    # this); must be reported as-is, not clamped to 100 or treated as an error.
    result = profitability_metrics(_AAPL)

    assert result.return_on_equity_pct == 148.75


def test_profitability_metrics_jpm_gross_margin_suppressed_others_not() -> None:
    result = profitability_metrics(_JPM)

    assert _JPM.sector == FINANCIAL_SERVICES_SECTOR
    assert result.gross_margin_pct is None
    assert result.operating_margin_pct == 50.39
    assert result.profit_margin_pct == 34.92
    assert result.return_on_equity_pct == 17.79


def test_valuation_multiples_jpm_enterprise_to_ebitda_none_from_absent_field() -> None:
    result = valuation_multiples(_JPM)

    # Currencies match here -- None comes purely from the raw field being absent.
    assert _JPM.currency == _JPM.financial_currency
    assert _JPM.enterprise_to_ebitda is None
    assert result.enterprise_to_ebitda is None
    assert result.trailing_pe == 15.06
    assert result.forward_pe == 14.06


def test_valuation_multiples_bhp_trailing_pe_not_gated_by_currency_mismatch() -> None:
    result = valuation_multiples(_BHP)

    assert _BHP.currency != _BHP.financial_currency
    assert result.trailing_pe == 24.76
    assert result.forward_pe == 18.62


def test_valuation_multiples_bhp_enterprise_to_ebitda_none_from_currency_mismatch() -> None:
    result = valuation_multiples(_BHP)

    # A real raw value exists (11.58) -- unlike JPM, this None comes specifically
    # from the currency gate, not from the field being absent.
    assert _BHP.currency != _BHP.financial_currency
    assert _BHP.enterprise_to_ebitda is not None
    assert result.enterprise_to_ebitda is None


def test_profitability_metrics_bhp_gross_margin_not_suppressed_non_financial_sector() -> None:
    result = profitability_metrics(_BHP)

    assert _BHP.sector != FINANCIAL_SERVICES_SECTOR
    assert result.gross_margin_pct == 85.92
    assert result.operating_margin_pct == 43.34
    assert result.profit_margin_pct == 16.73
    assert result.return_on_equity_pct == 24.0


def test_valuation_multiples_cba_enterprise_to_ebitda_none_from_absent_field_not_currency() -> None:
    # CBA.AX is ASX-listed like BHP.AX, but currency == financial_currency here
    # (AUD/AUD) -- its enterprise_to_ebitda=None takes the same "absent from raw
    # data" path as JPM's, structurally distinct from BHP.AX's currency-gated
    # None even though the final output is identical (None) in all three cases.
    result = valuation_multiples(_CBA)

    assert _CBA.currency == _CBA.financial_currency
    assert _CBA.enterprise_to_ebitda is None
    assert result.enterprise_to_ebitda is None


def test_profitability_metrics_cba_gross_margin_suppressed_financial_sector() -> None:
    result = profitability_metrics(_CBA)

    assert _CBA.sector == FINANCIAL_SERVICES_SECTOR
    assert result.gross_margin_pct is None
    assert result.operating_margin_pct == 56.2
    assert result.profit_margin_pct == 37.0
    assert result.return_on_equity_pct == 13.86
