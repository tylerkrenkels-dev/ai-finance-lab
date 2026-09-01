from datetime import UTC, datetime

from apps.equity_snapshot.calculations import ProfitabilityMetrics, ValuationMultiples
from apps.equity_snapshot.payload import EquitySnapshot, build_equity_snapshot
from apps.equity_snapshot.sources import RawFundamentals
from tests.apps.equity_snapshot.test_calculations import _AAPL, _BHP, _CBA, _JPM

# SYNTHETIC -- not real market data, unlike _BHP/_JPM above (imported from
# test_calculations.py, both real live-fetched values). Based on _AAPL's real
# field shape (Technology sector, currency == financial_currency, so neither
# policy gate applies) but with trailing_pe and gross_margins deliberately
# overridden to None -- not realistic for a real ticker with everything else
# populated, but that's the point: it exists purely to exercise payload.py's
# two generic "not available" warning branches (a field missing for neither
# the sector-suppression nor the currency-mismatch reason), which none of the
# four real investigated tickers happen to trigger. Do not treat this as a
# verified real-ticker fixture the way _AAPL/_JPM/_BHP/_CBA are.
_SYNTHETIC_MISSING_FIELDS = RawFundamentals(
    ticker="SYNTH",
    quote_type="EQUITY",
    company_name="Synthetic Test Corp",
    sector="Technology",
    currency="USD",
    financial_currency="USD",
    market_cap=1_000_000_000,
    enterprise_value=1_050_000_000,
    trailing_pe=None,
    forward_pe=20.0,
    price_to_book=5.0,
    price_to_sales_ttm=4.0,
    enterprise_to_ebitda=15.0,
    enterprise_to_revenue=4.5,
    trailing_eps=2.0,
    forward_eps=2.2,
    total_revenue=500_000_000,
    ebitda=100_000_000,
    gross_margins=None,
    operating_margins=0.25,
    profit_margins=0.15,
    return_on_equity=0.20,
    return_on_assets=0.10,
    debt_to_equity=40.0,
    current_ratio=1.5,
    quick_ratio=1.2,
    dividend_yield=1.0,
    beta=1.0,
    current_price=100.0,
    previous_close=99.0,
    fifty_two_week_high=120.0,
    fifty_two_week_low=80.0,
    free_cashflow=50_000_000,
    operating_cashflow=80_000_000,
    shares_outstanding=100_000_000,
    quote_as_of=datetime(2026, 1, 1, tzinfo=UTC),
    fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
)


def test_build_equity_snapshot_bhp_full_field_set() -> None:
    result = build_equity_snapshot(_BHP)

    assert result == EquitySnapshot(
        ticker="BHP.AX",
        company_name="BHP Group Limited",
        sector="Basic Materials",
        currency="AUD",
        current_price=67.1,
        market_cap=340878950400,
        market_cap_display="AUD 340.88 billion",
        as_of=datetime.fromtimestamp(1787532562, tz=UTC),
        valuation=ValuationMultiples(
            trailing_pe=24.76, forward_pe=18.62, enterprise_to_ebitda=None
        ),
        profitability=ProfitabilityMetrics(
            gross_margin_pct=85.92,
            operating_margin_pct=43.34,
            profit_margin_pct=16.73,
            return_on_equity_pct=24.0,
        ),
        data_warnings=[
            "EV/EBITDA not shown: BHP Group Limited's trading currency (AUD) differs "
            "from its reporting currency (USD)."
        ],
    )


def test_build_equity_snapshot_bhp_has_exactly_one_warning_no_spurious_ones() -> None:
    # gross_margin_pct is populated (Basic Materials, not Financial Services) and
    # trailing_pe/forward_pe/operating/profit/ROE are all populated -- only the
    # currency-gated enterprise_to_ebitda should produce a warning.
    result = build_equity_snapshot(_BHP)

    assert len(result.data_warnings) == 1
    assert "AUD" in result.data_warnings[0]
    assert "USD" in result.data_warnings[0]
    assert "BHP Group Limited" in result.data_warnings[0]


def test_build_equity_snapshot_jpm_full_field_set() -> None:
    result = build_equity_snapshot(_JPM)

    assert result == EquitySnapshot(
        ticker="JPM",
        company_name="JPMorgan Chase & Co.",
        sector="Financial Services",
        currency="USD",
        current_price=351.58,
        market_cap=934565052416,
        market_cap_display="USD 934.57 billion",
        as_of=datetime.fromtimestamp(1787342402, tz=UTC),
        valuation=ValuationMultiples(
            trailing_pe=15.06, forward_pe=14.06, enterprise_to_ebitda=None
        ),
        profitability=ProfitabilityMetrics(
            gross_margin_pct=None,
            operating_margin_pct=50.39,
            profit_margin_pct=34.92,
            return_on_equity_pct=17.79,
        ),
        data_warnings=[
            "Gross margin not shown: not economically meaningful for Financial Services companies.",
            "EV/EBITDA not available for this ticker.",
        ],
    )


def test_build_equity_snapshot_jpm_has_exactly_two_warnings_distinct_causes() -> None:
    # Both enterprise_to_ebitda (currency-matched but absent) and gross_margin_pct
    # (sector-suppressed) are None, for two DIFFERENT reasons -- the sector warning
    # must name the sector; the EV/EBITDA warning must be the generic one, not the
    # currency-mismatch wording BHP.AX gets, since JPM's currencies actually match.
    result = build_equity_snapshot(_JPM)

    assert len(result.data_warnings) == 2
    assert "Financial Services" in result.data_warnings[0]
    assert result.data_warnings[1] == "EV/EBITDA not available for this ticker."
    assert "currency" not in result.data_warnings[1]


def test_generic_missing_field_warning_for_a_field_with_no_specific_cause() -> None:
    # Uses _SYNTHETIC_MISSING_FIELDS (see comment above), a constructed edge case,
    # not real fetched data. trailing_pe=None here isn't caused by a sector or
    # currency policy (there is no P/E gate at all), and gross_margins=None isn't
    # sector-suppressed (sector is Technology, not Financial Services) -- both
    # should get the plain generic wording, not the specific BHP.AX/JPM-style text.
    result = build_equity_snapshot(_SYNTHETIC_MISSING_FIELDS)

    assert result.valuation.trailing_pe is None
    assert result.profitability.gross_margin_pct is None
    assert "Trailing P/E not available for this ticker." in result.data_warnings
    assert "Gross margin not available for this ticker." in result.data_warnings
    all_warnings = " ".join(result.data_warnings)
    assert "Financial Services" not in all_warnings
    assert "currency" not in all_warnings


# --- market_cap_display: one canonical, Python-computed form for the narrative
# to reproduce verbatim (see payload._format_market_cap). Expected strings below
# are hand-computed: raw / 10**scale, two decimal places, trailing zeros
# stripped, ISO 4217 code prefixed.


def test_market_cap_display_bhp_real_fixture_billions() -> None:
    # 340878950400 / 1e9 = 340.8789504 -> "340.88"
    assert build_equity_snapshot(_BHP).market_cap_display == "AUD 340.88 billion"


def test_market_cap_display_jpm_real_fixture_rounds_up() -> None:
    # 934565052416 / 1e9 = 934.565052416 -> rounds up to "934.57"
    assert build_equity_snapshot(_JPM).market_cap_display == "USD 934.57 billion"


def test_market_cap_display_aapl_real_fixture_trillions() -> None:
    # 4514709504000 >= 1e12 -> / 1e12 = 4.514709504 -> "4.51"
    assert build_equity_snapshot(_AAPL).market_cap_display == "USD 4.51 trillion"


def test_market_cap_display_cba_real_fixture_billions() -> None:
    # 259777396736 / 1e9 = 259.777396736 -> "259.78"
    assert build_equity_snapshot(_CBA).market_cap_display == "AUD 259.78 billion"


def _raw_with_market_cap(market_cap: int | None, currency: str = "USD") -> RawFundamentals:
    """A real fixture (_JPM) with only market_cap (and optionally currency)
    overridden -- for the _format_market_cap edge cases no real investigated
    ticker happens to hit. Clearly synthetic, like _SYNTHETIC_MISSING_FIELDS."""
    return _JPM.model_copy(update={"market_cap": market_cap, "currency": currency})


def test_market_cap_display_strips_trailing_zero() -> None:
    # 340900000000 / 1e9 = 340.9 exactly -> "340.90" -> "340.9", not "340.90"
    result = build_equity_snapshot(_raw_with_market_cap(340_900_000_000))
    assert result.market_cap_display == "USD 340.9 billion"


def test_market_cap_display_strips_to_bare_integer() -> None:
    # 500000000000 / 1e9 = 500.0 -> "500.00" -> "500", no decimal point
    result = build_equity_snapshot(_raw_with_market_cap(500_000_000_000))
    assert result.market_cap_display == "USD 500 billion"


def test_market_cap_display_million_is_the_floor_scale() -> None:
    # Below 1e9: million is the smallest scale word. 8500000 / 1e6 = 8.5.
    result = build_equity_snapshot(_raw_with_market_cap(8_500_000))
    assert result.market_cap_display == "USD 8.5 million"


def test_market_cap_display_is_none_when_market_cap_is_none() -> None:
    result = build_equity_snapshot(_raw_with_market_cap(None))
    assert result.market_cap is None
    assert result.market_cap_display is None
