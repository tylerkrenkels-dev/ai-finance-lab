from datetime import date, datetime

import pytest
from pydantic import ValidationError

from apps.macro_note.models import (
    CurveSlope,
    FxCarry,
    Metric,
    MetricChange,
    NoteFacts,
    NoteNarrative,
    Observation,
    Section,
    SeriesMeta,
)

_NO_CHANGE = MetricChange(pct_change=None, bp_change=None, reference_as_of=None)


def test_observation_construction() -> None:
    obs = Observation(
        series_id="us_10y",
        value=4.25,
        as_of=date(2026, 7, 30),
        fetched_at=datetime(2026, 7, 31, 6, 0, 0),
    )
    assert obs.series_id == "us_10y"
    assert obs.value == 4.25


def test_observation_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        Observation(series_id="us_10y", value=4.25, as_of=date(2026, 7, 30))  # type: ignore[call-arg]


def test_series_meta_construction() -> None:
    meta = SeriesMeta(
        series_id="us_10y",
        name="US 10-Year Treasury Yield",
        source="fred",
        source_code="DGS10",
        unit="%",
        category="rates",
    )
    assert meta.source == "fred"
    assert meta.category == "rates"


def test_series_meta_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError):
        SeriesMeta(
            series_id="us_10y",
            name="US 10-Year Treasury Yield",
            source="bloomberg",  # type: ignore[arg-type]
            source_code="DGS10",
            unit="%",
            category="rates",
        )


def test_metric_defaults_not_stale() -> None:
    metric = Metric(
        series_id="us_10y",
        label="US 10Y Yield",
        value=4.25,
        unit="%",
        as_of=date(2026, 7, 30),
        change_1d=_NO_CHANGE,
        change_1w=_NO_CHANGE,
        change_1m=_NO_CHANGE,
    )
    assert metric.stale is False
    assert metric.change_1d == _NO_CHANGE
    assert metric.stale_as_of is None


def test_metric_stale_with_marker() -> None:
    metric = Metric(
        series_id="us_10y",
        label="US 10Y Yield",
        value=4.25,
        unit="%",
        as_of=date(2026, 7, 28),
        change_1d=MetricChange(pct_change=0.5, bp_change=2.0, reference_as_of=date(2026, 7, 27)),
        change_1w=_NO_CHANGE,
        change_1m=_NO_CHANGE,
        stale=True,
        stale_as_of=date(2026, 7, 28),
    )
    assert metric.stale is True
    assert metric.stale_as_of == date(2026, 7, 28)


def test_note_facts_requires_at_least_one_section() -> None:
    with pytest.raises(ValidationError):
        NoteFacts(note_date=date(2026, 7, 31), sections=[])


def test_note_facts_construction() -> None:
    metric = Metric(
        series_id="us_10y",
        label="US 10Y Yield",
        value=4.25,
        unit="%",
        as_of=date(2026, 7, 30),
        change_1d=_NO_CHANGE,
        change_1w=_NO_CHANGE,
        change_1m=_NO_CHANGE,
    )
    section = Section(title="Rates", metrics=[metric])
    facts = NoteFacts(note_date=date(2026, 7, 31), sections=[section])
    assert facts.sections == [section]
    assert facts.data_warnings == []


def test_note_narrative_requires_at_least_one_bullet() -> None:
    with pytest.raises(ValidationError):
        NoteNarrative(headline="Markets steady", summary="Quiet session.", bullets=[])


def test_note_narrative_rejects_more_than_nine_bullets() -> None:
    with pytest.raises(ValidationError):
        NoteNarrative(
            headline="Markets steady",
            summary="Quiet session.",
            bullets=[f"Bullet {i}" for i in range(10)],
        )


def test_note_narrative_construction() -> None:
    narrative = NoteNarrative(
        headline="Yields tick higher",
        summary="US Treasury yields rose modestly overnight.",
        bullets=["US 10Y yield rose", "AUD/USD little changed"],
    )
    assert narrative.headline == "Yields tick higher"
    assert len(narrative.bullets) == 2


# --- Rounding at construction time (#39) ---
#
# Real values captured from #23's live dry run, which is what actually surfaced
# this bug: yfinance's raw copper close (6.5304999351501465 USD/lb) and the FX
# carry annualised return it produced (110.61247311827908%) showed up verbatim
# in the narrative while the rendered table independently rounded the same
# metric for display -- a visible mismatch. These fields now round once, at
# construction, so both consumers see the same number from the start.


def test_metric_value_rounds_to_two_decimals_for_percent_unit() -> None:
    metric = Metric(
        series_id="au_3y",
        label="AU 3-Year Government Bond Yield",
        value=4.4911111111111114,  # matches the shape of the real AU 3Y read during the dry run
        unit="%",
        as_of=date(2026, 7, 29),
        change_1d=_NO_CHANGE,
        change_1w=_NO_CHANGE,
        change_1m=_NO_CHANGE,
    )
    assert metric.value == 4.49


def test_metric_value_rounds_to_four_decimals_for_non_percent_unit() -> None:
    metric = Metric(
        series_id="copper",
        label="Copper",
        value=6.5304999351501465,  # the exact raw yfinance value from the #23 dry run
        unit="USD/lb",
        as_of=date(2026, 8, 2),
        change_1d=_NO_CHANGE,
        change_1w=_NO_CHANGE,
        change_1m=_NO_CHANGE,
    )
    assert metric.value == 6.5305


def test_metric_change_rounds_pct_to_two_and_bp_to_one_decimal() -> None:
    change = MetricChange(
        pct_change=1.4683043311721555,
        bp_change=-849.37123456,
        reference_as_of=date(2026, 7, 27),
    )
    assert change.pct_change == 1.47
    assert change.bp_change == -849.4


def test_metric_change_none_fields_stay_none() -> None:
    change = MetricChange(pct_change=None, bp_change=None, reference_as_of=None)
    assert change.pct_change is None
    assert change.bp_change is None


def test_curve_slope_spread_bp_rounds_to_one_decimal() -> None:
    slope = CurveSlope(
        label="AU 3s10s Slope",
        spread_bp=44.199999999999996,
        first_as_of=date(2026, 7, 29),
        second_as_of=date(2026, 7, 29),
    )
    assert slope.spread_bp == 44.2


def test_curve_slope_spread_bp_none_stays_none() -> None:
    slope = CurveSlope(label="US 2s10s Slope", spread_bp=None, first_as_of=None, second_as_of=None)
    assert slope.spread_bp is None


def test_fx_carry_pct_fields_round_to_two_decimals() -> None:
    # The exact raw values from the #23 dry run's "AUD/USD Carry (1D)" row.
    carry = FxCarry(
        label="AUD/USD Carry (1D)",
        annualised_return_pct=110.61247311827908,
        rate_differential_pct=0.7199999999999998,
        annualised_spot_change_pct=109.89247311827908,
        window_days=1,
    )
    assert carry.annualised_return_pct == 110.61
    assert carry.rate_differential_pct == 0.72
    assert carry.annualised_spot_change_pct == 109.89


def test_fx_carry_window_days_is_untouched_by_rounding() -> None:
    carry = FxCarry(
        label="AUD/USD Carry (1M)",
        annualised_return_pct=18.5420933043268,
        rate_differential_pct=0.72,
        annualised_spot_change_pct=17.82,
        window_days=30,
    )
    assert carry.window_days == 30
