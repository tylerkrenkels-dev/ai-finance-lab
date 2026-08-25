"""Assembles one ticker's RawFundamentals + calculations into EquitySnapshot.

EquitySnapshot is the complete, self-contained payload a future guarded
narrative call will see for one ticker -- the equivalent of
apps.macro_note.payload.build_note_facts, but per-ticker rather than
per-note, since this app has no store/history layer: a future orchestration
layer (not written yet) fetches RawFundamentals per ticker and calls
build_equity_snapshot() for each, the same way macro_note's main.py
populates the store before payload.build_note_facts reads from it.

No I/O here -- build_equity_snapshot() takes an already-fetched
RawFundamentals, mirroring calculations.py's "no I/O" rule one layer up and
apps.macro_note.payload.build_note_facts's own signature (it takes an
already-populated store, not a fetch call).

data_warnings mirrors apps.macro_note.payload's same-named mechanism: rather
than adding a "why is this None" field to ValuationMultiples/
ProfitabilityMetrics (which would re-open the exact "duplicate the sector
info" problem calculations.py's policies were designed to avoid), a specific,
human-readable reason is generated here for every None field -- naming the
sector or the currency mismatch when calculations.py's public
is_sector_inapplicable/currencies_match say that's why, and a generic
"not available" message otherwise (a field genuinely absent from yfinance).
This reuses calculations.py's policy decisions rather than re-deriving them,
so the policy stays defined in exactly one place.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.equity_snapshot.calculations import (
    ProfitabilityMetrics,
    ValuationMultiples,
    currencies_match,
    is_sector_inapplicable,
    profitability_metrics,
    valuation_multiples,
)
from apps.equity_snapshot.sources import RawFundamentals


class EquitySnapshot(BaseModel):
    """Complete per-ticker snapshot payload -- the only input a guarded
    narrative call for one ticker will ever see."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    company_name: str
    sector: str | None
    currency: str  # trading currency -- labels current_price/market_cap below
    current_price: float
    market_cap: int | None
    as_of: datetime

    valuation: ValuationMultiples
    profitability: ProfitabilityMetrics

    data_warnings: list[str] = Field(default_factory=list)

    @field_validator("current_price")
    @classmethod
    def _round_price(cls, v: float) -> float:
        return round(v, 2)


def build_equity_snapshot(fundamentals: RawFundamentals) -> EquitySnapshot:
    """Assemble the full EquitySnapshot payload for one ticker. No I/O."""
    valuation = valuation_multiples(fundamentals)
    profitability = profitability_metrics(fundamentals)
    return EquitySnapshot(
        ticker=fundamentals.ticker,
        company_name=fundamentals.company_name,
        sector=fundamentals.sector,
        currency=fundamentals.currency,
        current_price=fundamentals.current_price,
        market_cap=fundamentals.market_cap,
        as_of=fundamentals.quote_as_of,
        valuation=valuation,
        profitability=profitability,
        data_warnings=_build_warnings(fundamentals, valuation, profitability),
    )


def _build_warnings(
    fundamentals: RawFundamentals,
    valuation: ValuationMultiples,
    profitability: ProfitabilityMetrics,
) -> list[str]:
    warnings: list[str] = []

    if profitability.gross_margin_pct is None:
        if is_sector_inapplicable(fundamentals, "gross_margins"):
            warnings.append(
                "Gross margin not shown: not economically meaningful for "
                f"{fundamentals.sector} companies."
            )
        else:
            warnings.append("Gross margin not available for this ticker.")

    if valuation.enterprise_to_ebitda is None:
        if not currencies_match(fundamentals):
            warnings.append(
                f"EV/EBITDA not shown: {fundamentals.company_name}'s trading currency "
                f"({fundamentals.currency}) differs from its reporting currency "
                f"({fundamentals.financial_currency})."
            )
        else:
            warnings.append("EV/EBITDA not available for this ticker.")

    _warn_if_missing(warnings, "Trailing P/E", valuation.trailing_pe)
    _warn_if_missing(warnings, "Forward P/E", valuation.forward_pe)
    _warn_if_missing(warnings, "Operating margin", profitability.operating_margin_pct)
    _warn_if_missing(warnings, "Profit margin", profitability.profit_margin_pct)
    _warn_if_missing(warnings, "Return on equity", profitability.return_on_equity_pct)

    return warnings


def _warn_if_missing(warnings: list[str], label: str, value: float | None) -> None:
    if value is None:
        warnings.append(f"{label} not available for this ticker.")
