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

market_cap_display is a formatted string ("AUD 340.88 billion") computed once
in _format_market_cap. It exists so the narrative has a single canonical form
to reproduce verbatim: without it, a model turning the raw 340878950400 into
"~A$341 billion" is doing arithmetic the core invariant forbids, and a numeric
guard would either have to block that correct-looking prose or accept a whole
family of derived roundings. Rounding once, here in Python, is the same fix
macro_note applied when an analogous multi-form figure caused false guard hits.
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

_TRILLION = 1_000_000_000_000
_BILLION = 1_000_000_000
_MILLION = 1_000_000


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
    # Pre-formatted, human-readable rendering of market_cap (e.g. "AUD 340.88
    # billion"), computed once in _format_market_cap so the narrative has exactly
    # one canonical figure to reproduce verbatim -- not a family of model-derived
    # roundings of the raw integer. None exactly when market_cap is None.
    market_cap_display: str | None
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
        market_cap_display=_format_market_cap(fundamentals.market_cap, fundamentals.currency),
        as_of=fundamentals.quote_as_of,
        valuation=valuation,
        profitability=profitability,
        data_warnings=_build_warnings(fundamentals, valuation, profitability),
    )


def _format_market_cap(market_cap: int | None, currency: str) -> str | None:
    """Human-readable market cap (e.g. "AUD 340.88 billion") for the narrative to
    reproduce verbatim.

    Computed once here so there is exactly one canonical figure the numeric
    fidelity guard can trace against, rather than a family of model-derived
    roundings of the raw integer. Mirrors the "round once at the boundary"
    discipline calculations.py already applies to every ratio: two decimal
    places (its _ROUND_DIGITS), trailing zeros stripped, ISO 4217 code as the
    prefix so there is no A$/US$/NZ$ ambiguity and no symbol table to maintain.
    None exactly when market_cap is None.
    """
    if market_cap is None:
        return None
    if market_cap >= _TRILLION:
        scaled, word = market_cap / _TRILLION, "trillion"
    elif market_cap >= _BILLION:
        scaled, word = market_cap / _BILLION, "billion"
    else:
        scaled, word = market_cap / _MILLION, "million"
    number = f"{scaled:.2f}".rstrip("0").rstrip(".")
    return f"{currency} {number} {word}"


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
