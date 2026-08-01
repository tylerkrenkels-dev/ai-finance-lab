from datetime import date, datetime

import pytest
from pydantic import ValidationError

from apps.macro_note.models import (
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


def test_note_narrative_construction() -> None:
    narrative = NoteNarrative(
        headline="Yields tick higher",
        summary="US Treasury yields rose modestly overnight.",
        bullets=["US 10Y yield rose", "AUD/USD little changed"],
    )
    assert narrative.headline == "Yields tick higher"
    assert len(narrative.bullets) == 2
