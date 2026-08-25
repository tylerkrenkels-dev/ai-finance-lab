"""Pure valuation and profitability calculations from a RawFundamentals snapshot.

No I/O, no network, no clock reads. Every function here takes the whole
RawFundamentals for one ticker (already the single per-ticker unit fetched by
sources.py, unlike macro_note's per-series Observation) and applies the two
policy decisions sources.py deliberately deferred:

1. Sector-inapplicability. A present, structurally valid value can still be
   economically meaningless for a given sector -- confirmed empirically:
   gross_margins=0.0 for a bank is real (banks have no COGS) but not
   informative. _SECTOR_INAPPLICABLE_FIELDS is the one place this policy is
   written down; nothing else in this module hardcodes a sector string.
   operating_margins/profit_margins/return_on_equity are NOT suppressed for
   financials -- those are standard, meaningful bank metrics, confirmed
   present and sane in the investigation (JPM operating_margins=50.4%,
   profit_margins=34.9%).

2. Currency mismatch. Confirmed live against BHP.AX and AAPL that every
   yfinance ratio field is an honest division of two other raw fields in the
   same .info dict, with no hidden FX step -- so a ratio's trustworthiness
   depends entirely on whether its two raw inputs are actually in the same
   currency. Checked which of RawFundamentals's fields are: trailingEps and
   bookValue track the trading currency (BHP.AX: currentPrice/trailingEps
   equals trailingPE exactly), while totalRevenue/ebitda stay in
   financial_currency, unconverted (BHP.AX's totalRevenue is USD-scale, not
   AUD-scale). So trailing_pe/forward_pe are safe under a currency mismatch;
   enterprise_to_ebitda is not (EV tracks trading currency via market cap,
   EBITDA tracks financial_currency) -- BHP.AX's own enterpriseToEbitda is
   very likely wrong by roughly the AUD/USD rate. Margins and ROE are pure
   financial-statement ratios (net income / revenue, both in
   financial_currency) with no price component, so they were never at risk in
   the first place and are not gated. This app has no FX source, so "can't
   safely compute" means None, not a converted guess.
"""

from pydantic import BaseModel, ConfigDict, field_validator

from apps.equity_snapshot.sources import RawFundamentals

FINANCIAL_SERVICES_SECTOR = "Financial Services"  # yfinance's own sector string,
# confirmed live against JPM and CBA.AX

# Fields that are numerically present-and-valid but not economically meaningful for a
# given sector -- distinct from genuinely missing fields (already None from
# sources.py). Only gross_margins is suppressed: operating/profit margins and ROE
# are real, standard bank metrics and must not be swept into the same rule.
_SECTOR_INAPPLICABLE_FIELDS: dict[str, frozenset[str]] = {
    FINANCIAL_SERVICES_SECTOR: frozenset({"gross_margins"}),
}

_ROUND_DIGITS = 2


def _round_or_none(value: float | None, digits: int = _ROUND_DIGITS) -> float | None:
    return value if value is None else round(value, digits)


def is_sector_inapplicable(fundamentals: RawFundamentals, field_name: str) -> bool:
    """True if `field_name` is economically meaningless for fundamentals.sector.

    Public so payload.py can explain a suppressed field in a data_warning
    without re-implementing this policy table a second time.
    """
    suppressed = _SECTOR_INAPPLICABLE_FIELDS.get(fundamentals.sector or "", frozenset())
    return field_name in suppressed


def currencies_match(fundamentals: RawFundamentals) -> bool:
    """True if fundamentals.currency == fundamentals.financial_currency.

    Public for the same reason as is_sector_inapplicable: payload.py needs it
    to explain a currency-gated field, not to re-decide the gate itself.
    """
    return fundamentals.currency == fundamentals.financial_currency


class ValuationMultiples(BaseModel):
    """P/E and EV/EBITDA for one ticker, rounded once here (not re-rounded
    downstream), mirroring apps.macro_note.models.Metric's rounding-at-the-
    boundary discipline. None means couldn't be computed -- not zero, not an
    error: either yfinance didn't have the field, or (enterprise_to_ebitda
    only) the ticker's price and financials currencies don't match.
    """

    model_config = ConfigDict(frozen=True)

    trailing_pe: float | None
    forward_pe: float | None
    enterprise_to_ebitda: float | None

    @field_validator("trailing_pe", "forward_pe", "enterprise_to_ebitda")
    @classmethod
    def _round(cls, v: float | None) -> float | None:
        return _round_or_none(v)


class ProfitabilityMetrics(BaseModel):
    """Gross/operating/profit margin and ROE, always percent-scale (e.g. 27.6
    means 27.6%). RawFundamentals stores these as fractions (0.276); this is
    the one place that conversion happens, closing the same scale trap
    RawFundamentals.dividend_yield's docstring flags for that field, rather
    than leaving each consumer to independently guess or re-derive it. None
    means couldn't be computed -- not zero, not an error: either yfinance
    didn't have the field, or (gross_margin_pct only) it's a real but
    sector-inapplicable value (see module docstring, policy 1).
    """

    model_config = ConfigDict(frozen=True)

    gross_margin_pct: float | None
    operating_margin_pct: float | None
    profit_margin_pct: float | None
    return_on_equity_pct: float | None

    @field_validator(
        "gross_margin_pct", "operating_margin_pct", "profit_margin_pct", "return_on_equity_pct"
    )
    @classmethod
    def _round(cls, v: float | None) -> float | None:
        return _round_or_none(v)


def valuation_multiples(fundamentals: RawFundamentals) -> ValuationMultiples:
    """P/E (trailing, forward) and EV/EBITDA for `fundamentals`.

    enterprise_to_ebitda is None whenever currency != financial_currency --
    see module docstring, policy 2. trailing_pe/forward_pe are not gated:
    confirmed safe under a currency mismatch.
    """
    enterprise_to_ebitda = (
        fundamentals.enterprise_to_ebitda if currencies_match(fundamentals) else None
    )
    return ValuationMultiples(
        trailing_pe=fundamentals.trailing_pe,
        forward_pe=fundamentals.forward_pe,
        enterprise_to_ebitda=enterprise_to_ebitda,
    )


def profitability_metrics(fundamentals: RawFundamentals) -> ProfitabilityMetrics:
    """Gross/operating/profit margin and ROE for `fundamentals`, as percentages.

    gross_margin_pct is None when the ticker's sector makes gross margin
    economically meaningless (see module docstring, policy 1), even though
    RawFundamentals.gross_margins holds a real, present value in that case.
    """
    gross_margins = (
        None
        if is_sector_inapplicable(fundamentals, "gross_margins")
        else fundamentals.gross_margins
    )
    return ProfitabilityMetrics(
        gross_margin_pct=_to_percent(gross_margins),
        operating_margin_pct=_to_percent(fundamentals.operating_margins),
        profit_margin_pct=_to_percent(fundamentals.profit_margins),
        return_on_equity_pct=_to_percent(fundamentals.return_on_equity),
    )


def _to_percent(fraction: float | None) -> float | None:
    return fraction if fraction is None else fraction * 100
