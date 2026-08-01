"""Assembles Metrics and derived figures into NoteFacts -- the only payload an LLM call ever sees.

Iterates the registry, builds a Metric per series via metrics.py, groups them
into Sections by SeriesMeta.category, and separately computes the cross-series
derived figures (curve slopes, FX carry) that don't fit a single series_id.
Generates data_warnings for anything stale or entirely uncomputable, rather
than silently dropping it.
"""

from datetime import date

from apps.macro_note.calculations.fx import one_day_carry, one_month_carry, one_week_carry
from apps.macro_note.calculations.rates import au_3s10s_slope, au_us_10y_spread, us_2s10s_slope
from apps.macro_note.metrics import HISTORY_LOOKBACK, build_metric
from apps.macro_note.models import CurveSlope, FxCarry, Metric, NoteFacts, Section
from apps.macro_note.registry import SERIES_REGISTRY
from apps.macro_note.store import ObservationStore

CATEGORY_TITLES: dict[str, str] = {
    "rates": "Rates",
    "inflation": "Inflation",
    "fx": "FX",
    "commodities": "Commodities",
    "equities": "Equities",
}

# Rates and inflation first, most central to a macro note; curve slopes attach
# to "rates", FX carry attaches to "fx".
SECTION_ORDER = ["rates", "inflation", "fx", "commodities", "equities"]


def build_note_facts(store: ObservationStore, note_date: date) -> NoteFacts:
    """Assemble the full NoteFacts payload for note_date from the current store state."""
    warnings: list[str] = []
    metrics_by_category = _build_metrics(store, note_date, warnings)
    curve_slopes = _build_curve_slopes(store, warnings)
    fx_carry = _build_fx_carry(store, warnings)

    sections: list[Section] = []
    for category in SECTION_ORDER:
        section_metrics = metrics_by_category.get(category, [])
        section_curve_slopes = curve_slopes if category == "rates" else []
        section_fx_carry = fx_carry if category == "fx" else []
        if not section_metrics and not section_curve_slopes and not section_fx_carry:
            continue
        sections.append(
            Section(
                title=CATEGORY_TITLES[category],
                metrics=section_metrics,
                curve_slopes=section_curve_slopes,
                fx_carry=section_fx_carry,
            )
        )

    return NoteFacts(note_date=note_date, sections=sections, data_warnings=warnings)


def _build_metrics(
    store: ObservationStore, note_date: date, warnings: list[str]
) -> dict[str, list[Metric]]:
    metrics_by_category: dict[str, list[Metric]] = {}
    for series_meta in SERIES_REGISTRY:
        metric = build_metric(series_meta, store, note_date)
        if metric is None:
            warnings.append(f"No data available for {series_meta.name}.")
            continue
        if metric.stale and metric.stale_as_of is not None:
            gap_days = (note_date - metric.stale_as_of).days
            warnings.append(
                f"{metric.label} is stale: last updated {metric.stale_as_of.isoformat()} "
                f"({gap_days} days ago)."
            )
        metrics_by_category.setdefault(series_meta.category, []).append(metric)
    return metrics_by_category


def _build_curve_slopes(store: ObservationStore, warnings: list[str]) -> list[CurveSlope]:
    candidates = [
        ("US 2s10s Slope", us_2s10s_slope(store.latest("us_2y"), store.latest("us_10y"))),
        ("AU 3s10s Slope", au_3s10s_slope(store.latest("au_3y"), store.latest("au_10y"))),
        ("AU-US 10Y Spread", au_us_10y_spread(store.latest("us_10y"), store.latest("au_10y"))),
    ]
    slopes: list[CurveSlope] = []
    for label, spread in candidates:
        # Spread is symmetric: spread_bp is None if and only if both dates are too.
        if spread.spread_bp is None:
            warnings.append(f"{label} could not be computed (missing input data).")
            continue
        slopes.append(
            CurveSlope(
                label=label,
                spread_bp=spread.spread_bp,
                first_as_of=spread.first_as_of,
                second_as_of=spread.second_as_of,
            )
        )
    return slopes


def _build_fx_carry(store: ObservationStore, warnings: list[str]) -> list[FxCarry]:
    au_cash_rate = store.latest("au_cash_rate")
    us_fed_funds = store.latest("us_fed_funds")
    aud_usd_history = store.history("aud_usd", lookback=HISTORY_LOOKBACK)

    candidates = [
        ("AUD/USD Carry (1D)", one_day_carry(au_cash_rate, us_fed_funds, aud_usd_history)),
        ("AUD/USD Carry (1W)", one_week_carry(au_cash_rate, us_fed_funds, aud_usd_history)),
        ("AUD/USD Carry (1M)", one_month_carry(au_cash_rate, us_fed_funds, aud_usd_history)),
    ]
    carries: list[FxCarry] = []
    for label, carry in candidates:
        # Carry is deliberately asymmetric (see fx.Carry): a sub-component can be
        # populated even when the combined figure isn't. Only drop this entry if
        # every field failed -- dropping on annualised_return_pct alone would
        # throw away a partial result Carry was specifically designed to keep.
        if (
            carry.annualised_return_pct is None
            and carry.rate_differential_pct is None
            and carry.annualised_spot_change_pct is None
        ):
            warnings.append(f"{label} could not be computed (missing input data).")
            continue
        carries.append(
            FxCarry(
                label=label,
                annualised_return_pct=carry.annualised_return_pct,
                rate_differential_pct=carry.rate_differential_pct,
                annualised_spot_change_pct=carry.annualised_spot_change_pct,
                window_days=carry.window_days,
            )
        )
    return carries
