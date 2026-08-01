from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.macro_note.models import NoteFacts, Observation
from apps.macro_note.payload import build_note_facts
from apps.macro_note.store import ObservationStore

NOTE_DATE = date(2026, 7, 31)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ObservationStore]:
    s = ObservationStore(data_dir=tmp_path)
    yield s
    s.close()


def _obs(series_id: str, as_of: date, value: float) -> Observation:
    return Observation(series_id=series_id, value=value, as_of=as_of, fetched_at=datetime.now(UTC))


def _seed_month(store: ObservationStore, series_id: str, source: str, latest_value: float) -> None:
    """Populate ~5 weeks of weekday-only history ending at NOTE_DATE, for change calcs."""
    for i in range(35):
        d = NOTE_DATE - timedelta(days=34 - i)
        if d.weekday() < 5:
            store.upsert([_obs(series_id, d, latest_value - (34 - i) * 0.001)], source=source)


def test_metrics_grouped_into_sections_by_category(store: ObservationStore) -> None:
    _seed_month(store, "us_10y", "fred", 4.25)
    _seed_month(store, "gold", "yfinance", 1950.0)

    facts = build_note_facts(store, NOTE_DATE)

    titles = [s.title for s in facts.sections]
    assert titles == ["Rates", "Commodities"]

    rates_section = next(s for s in facts.sections if s.title == "Rates")
    assert any(m.series_id == "us_10y" for m in rates_section.metrics)

    commodities_section = next(s for s in facts.sections if s.title == "Commodities")
    assert any(m.series_id == "gold" for m in commodities_section.metrics)


def test_stale_metric_produces_data_warning(store: ObservationStore) -> None:
    stale_date = NOTE_DATE - timedelta(days=10)
    store.upsert([_obs("us_cpi_yoy", stale_date, 3.10)], source="fred")

    facts = build_note_facts(store, NOTE_DATE)

    inflation_section = next(s for s in facts.sections if s.title == "Inflation")
    metric = inflation_section.metrics[0]
    assert metric.stale is True
    assert metric.stale_as_of == stale_date
    assert (
        "US CPI (Year-over-Year) is stale: last updated 2026-07-21 (10 days ago)."
        in facts.data_warnings
    )


def test_fresh_weekend_gap_is_not_flagged_stale(store: ObservationStore) -> None:
    # Friday close, note run on the following Monday: a 3-day gap, within the threshold.
    friday = NOTE_DATE - timedelta(days=3)
    store.upsert([_obs("us_cpi_yoy", friday, 3.10)], source="fred")

    facts = build_note_facts(store, NOTE_DATE)

    inflation_section = next(s for s in facts.sections if s.title == "Inflation")
    metric = inflation_section.metrics[0]
    assert metric.stale is False
    assert metric.stale_as_of is None
    assert not any("US CPI" in warning for warning in facts.data_warnings)


def test_missing_series_produces_warning_and_is_omitted(store: ObservationStore) -> None:
    _seed_month(store, "us_10y", "fred", 4.25)
    # us_2y is never populated at all.

    facts = build_note_facts(store, NOTE_DATE)

    rates_section = next(s for s in facts.sections if s.title == "Rates")
    assert all(m.series_id != "us_2y" for m in rates_section.metrics)
    assert "No data available for US 2-Year Treasury Yield." in facts.data_warnings


def test_curve_slopes_attach_to_rates_section(store: ObservationStore) -> None:
    _seed_month(store, "us_2y", "fred", 3.85)
    _seed_month(store, "us_10y", "fred", 4.25)

    facts = build_note_facts(store, NOTE_DATE)

    rates_section = next(s for s in facts.sections if s.title == "Rates")
    labels = [cs.label for cs in rates_section.curve_slopes]
    assert "US 2s10s Slope" in labels
    other_sections = [s for s in facts.sections if s.title != "Rates"]
    assert all(s.curve_slopes == [] for s in other_sections)


def test_fx_carry_attaches_to_fx_section(store: ObservationStore) -> None:
    _seed_month(store, "aud_usd", "fred", 0.6600)
    store.upsert([_obs("au_cash_rate", NOTE_DATE, 4.35)], source="rba")
    store.upsert([_obs("us_fed_funds", NOTE_DATE, 4.50)], source="fred")

    facts = build_note_facts(store, NOTE_DATE)

    fx_section = next(s for s in facts.sections if s.title == "FX")
    labels = [fc.label for fc in fx_section.fx_carry]
    assert labels == ["AUD/USD Carry (1D)", "AUD/USD Carry (1W)", "AUD/USD Carry (1M)"]
    other_sections = [s for s in facts.sections if s.title != "FX"]
    assert all(s.fx_carry == [] for s in other_sections)


def test_curve_slope_omitted_and_warned_when_a_leg_is_entirely_missing(
    store: ObservationStore,
) -> None:
    _seed_month(store, "us_10y", "fred", 4.25)
    # us_2y never populated -> US 2s10s Slope can't be computed at all.

    facts = build_note_facts(store, NOTE_DATE)

    rates_section = next(s for s in facts.sections if s.title == "Rates")
    labels = [cs.label for cs in rates_section.curve_slopes]
    assert "US 2s10s Slope" not in labels
    assert "US 2s10s Slope could not be computed (missing input data)." in facts.data_warnings


def test_empty_category_is_dropped_entirely(store: ObservationStore) -> None:
    _seed_month(store, "us_10y", "fred", 4.25)
    # No gold/copper/asx200 data at all -> Commodities and Equities sections
    # should not appear, not appear empty.

    facts = build_note_facts(store, NOTE_DATE)

    titles = [s.title for s in facts.sections]
    assert "Commodities" not in titles
    assert "Equities" not in titles


def test_total_blackout_raises_validation_error(store: ObservationStore) -> None:
    # Nothing populated for any registered series at all.
    with pytest.raises(ValidationError):
        build_note_facts(store, NOTE_DATE)


def test_returns_note_facts_instance(store: ObservationStore) -> None:
    _seed_month(store, "us_10y", "fred", 4.25)

    facts = build_note_facts(store, NOTE_DATE)

    assert isinstance(facts, NoteFacts)
    assert facts.note_date == NOTE_DATE
