from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from apps.macro_note.models import Observation
from apps.macro_note.store import ObservationStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ObservationStore]:
    s = ObservationStore(data_dir=tmp_path)
    yield s
    s.close()


def _obs(
    series_id: str = "us_10y",
    value: float = 4.25,
    as_of: date = date(2026, 7, 30),
    fetched_at: datetime = datetime(2026, 7, 31, 6, 0, tzinfo=UTC),
) -> Observation:
    return Observation(series_id=series_id, value=value, as_of=as_of, fetched_at=fetched_at)


def test_upsert_and_latest(store: ObservationStore) -> None:
    store.upsert([_obs()], source="fred")

    result = store.latest("us_10y")

    assert result is not None
    assert result.value == 4.25
    assert result.as_of == date(2026, 7, 30)


def test_latest_returns_none_for_unknown_series(store: ObservationStore) -> None:
    assert store.latest("nonexistent") is None


def test_upsert_is_idempotent_no_duplicate_row(store: ObservationStore) -> None:
    obs = _obs()
    store.upsert([obs], source="fred")
    store.upsert([obs], source="fred")

    history = store.history("us_10y", lookback=10)

    assert len(history) == 1


def test_upsert_revision_replaces_value_not_appends(store: ObservationStore) -> None:
    original = _obs(value=4.25, fetched_at=datetime(2026, 7, 31, 6, 0, tzinfo=UTC))
    revised = _obs(value=4.30, fetched_at=datetime(2026, 7, 31, 18, 0, tzinfo=UTC))

    store.upsert([original], source="fred")
    store.upsert([revised], source="fred")

    latest = store.latest("us_10y")
    history = store.history("us_10y", lookback=10)

    assert latest is not None
    assert latest.value == 4.30
    assert len(history) == 1


def test_upsert_with_empty_list_is_noop(store: ObservationStore) -> None:
    store.upsert([], source="fred")

    assert store.latest("us_10y") is None


def test_history_respects_lookback_and_orders_oldest_first(store: ObservationStore) -> None:
    days = [date(2026, 7, d) for d in range(20, 25)]
    observations = [_obs(value=float(i), as_of=day) for i, day in enumerate(days)]
    store.upsert(observations, source="fred")

    history = store.history("us_10y", lookback=3)

    assert [obs.as_of for obs in history] == days[-3:]
    assert [obs.value for obs in history] == [2.0, 3.0, 4.0]


def test_history_scoped_to_series_id(store: ObservationStore) -> None:
    store.upsert([_obs(series_id="us_10y", value=4.25)], source="fred")
    store.upsert([_obs(series_id="us_2y", value=3.90)], source="fred")

    us_10y_history = store.history("us_10y", lookback=10)
    us_2y_history = store.history("us_2y", lookback=10)

    assert [obs.value for obs in us_10y_history] == [4.25]
    assert [obs.value for obs in us_2y_history] == [3.90]


def test_upsert_writes_parquet_export(store: ObservationStore, tmp_path: Path) -> None:
    store.upsert([_obs()], source="fred")

    parquet_path = tmp_path / "observations.parquet"
    assert parquet_path.exists()

    import duckdb

    rows = duckdb.sql(f"SELECT series_id, value FROM read_parquet('{parquet_path}')").fetchall()
    assert rows == [("us_10y", 4.25)]


def test_data_persists_across_close_and_reopen(tmp_path: Path) -> None:
    first = ObservationStore(data_dir=tmp_path)
    first.upsert([_obs()], source="fred")
    first.close()

    second = ObservationStore(data_dir=tmp_path)
    try:
        result = second.latest("us_10y")
    finally:
        second.close()

    assert result is not None
    assert result.value == 4.25
