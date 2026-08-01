from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from apps.macro_note.metrics import build_metric
from apps.macro_note.models import Observation, SeriesMeta
from apps.macro_note.store import ObservationStore

US_10Y = SeriesMeta(
    series_id="us_10y",
    name="US 10-Year Treasury Yield",
    source="fred",
    source_code="DGS10",
    unit="%",
    category="rates",
)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ObservationStore]:
    s = ObservationStore(data_dir=tmp_path)
    yield s
    s.close()


def _seed(store: ObservationStore, as_of: date, value: float = 4.25) -> None:
    obs = Observation(series_id="us_10y", value=value, as_of=as_of, fetched_at=datetime.now(UTC))
    store.upsert([obs], source="fred")


def test_exactly_at_threshold_is_not_stale(store: ObservationStore) -> None:
    # gap_days = 4 (2026-07-20 minus 2026-07-16)
    _seed(store, date(2026, 7, 16))

    metric = build_metric(US_10Y, store, note_date=date(2026, 7, 20))

    assert metric is not None
    assert metric.stale is False
    assert metric.stale_as_of is None


def test_one_day_over_threshold_is_stale(store: ObservationStore) -> None:
    # gap_days = 5 (2026-07-20 minus 2026-07-15)
    _seed(store, date(2026, 7, 15))

    metric = build_metric(US_10Y, store, note_date=date(2026, 7, 20))

    assert metric is not None
    assert metric.stale is True
    assert metric.stale_as_of == date(2026, 7, 15)


def test_ordinary_weekend_gap_is_not_stale(store: ObservationStore) -> None:
    # gap_days = 3 (Friday 2026-07-17 to Monday 2026-07-20) -- the case that would
    # have been a false positive under a naive "stale = not today" rule.
    _seed(store, date(2026, 7, 17))

    metric = build_metric(US_10Y, store, note_date=date(2026, 7, 20))

    assert metric is not None
    assert metric.stale is False
    assert metric.stale_as_of is None


def test_same_day_no_gap_is_not_stale(store: ObservationStore) -> None:
    # gap_days = 0
    _seed(store, date(2026, 7, 20))

    metric = build_metric(US_10Y, store, note_date=date(2026, 7, 20))

    assert metric is not None
    assert metric.stale is False
    assert metric.stale_as_of is None


def test_no_history_returns_none(store: ObservationStore) -> None:
    metric = build_metric(US_10Y, store, note_date=date(2026, 7, 20))

    assert metric is None


def test_metric_fields_populated_from_series_meta_and_latest_observation(
    store: ObservationStore,
) -> None:
    _seed(store, date(2026, 7, 20), value=4.25)

    metric = build_metric(US_10Y, store, note_date=date(2026, 7, 20))

    assert metric is not None
    assert metric.series_id == "us_10y"
    assert metric.label == "US 10-Year Treasury Yield"
    assert metric.value == 4.25
    assert metric.unit == "%"
    assert metric.as_of == date(2026, 7, 20)
