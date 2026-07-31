from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from apps.macro_note.models import Observation
from apps.macro_note.sources.base import SourceProvider
from apps.macro_note.sources.rba import RbaConnectorError, RbaSource

FIXTURES_DIR = Path(__file__).parent / "fixtures"

CASH_RATE_URL = "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv"

NO_SERIES_ID_ROW_CSV = (
    "F1 INTEREST RATES AND YIELDS - MONEY MARKET\n"
    "Title,Cash Rate Target\n"
    "Units,Per cent\n"
    "27-Jul-2026,4.35\n"
)

UNKNOWN_SERIES_CODE_CSV = (
    "F1 INTEREST RATES AND YIELDS - MONEY MARKET\n"
    "Title,Cash Rate Target\n"
    "Units,Per cent\n"
    "Series ID,SOME_OTHER_CODE\n"
    "27-Jul-2026,4.35\n"
)


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _mock_response(text: str, status_code: int = 200, url: str = CASH_RATE_URL) -> httpx.Response:
    return httpx.Response(
        status_code, content=text.encode("utf-8"), request=httpx.Request("GET", url)
    )


def test_rba_source_implements_source_provider() -> None:
    assert isinstance(RbaSource(), SourceProvider)


def test_fetch_observations_selects_correct_column_and_filters_missing() -> None:
    fixture = _load_fixture("rba_f1_cash_rate.csv")
    source = RbaSource()

    with patch("httpx.get", return_value=_mock_response(fixture)) as mock_get:
        observations = source.fetch_observations(
            series_id="au_cash_rate",
            source_code="FIRMMCRTD",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )

    mock_get.assert_called_once()
    # 31-Jul is truncated in the fixture (no value reported yet that day) and must
    # be excluded, not read as an IndexError or coerced to 0.0.
    assert len(observations) == 4
    assert all(isinstance(obs, Observation) for obs in observations)
    assert all(obs.series_id == "au_cash_rate" for obs in observations)
    assert all(obs.value == 4.35 for obs in observations)
    assert [obs.as_of for obs in observations] == [
        date(2026, 7, 27),
        date(2026, 7, 28),
        date(2026, 7, 29),
        date(2026, 7, 30),
    ]


def test_fetch_observations_selects_a_different_column_correctly() -> None:
    fixture = _load_fixture("rba_f1_cash_rate.csv")
    source = RbaSource()

    # FIRMMCRID isn't one of the 3 registry series, so it isn't in the real TABLE_URLS.
    # This test is only exercising column selection within a table, not the table lookup.
    with (
        patch.dict("apps.macro_note.sources.rba.TABLE_URLS", {"FIRMMCRID": CASH_RATE_URL}),
        patch("httpx.get", return_value=_mock_response(fixture)),
    ):
        observations = source.fetch_observations(
            series_id="au_interbank",
            source_code="FIRMMCRID",
            start=date(2026, 7, 27),
            end=date(2026, 7, 30),
        )

    assert len(observations) == 4
    assert all(obs.value == 4.35 for obs in observations)


def test_fetch_observations_respects_date_range() -> None:
    fixture = _load_fixture("rba_f1_cash_rate.csv")
    source = RbaSource()

    with patch("httpx.get", return_value=_mock_response(fixture)):
        observations = source.fetch_observations(
            series_id="au_cash_rate",
            source_code="FIRMMCRTD",
            start=date(2026, 7, 28),
            end=date(2026, 7, 29),
        )

    assert [obs.as_of for obs in observations] == [date(2026, 7, 28), date(2026, 7, 29)]


def test_fetch_observations_raises_when_source_code_unmapped() -> None:
    source = RbaSource()

    with (
        patch("httpx.get") as mock_get,
        pytest.raises(RbaConnectorError, match="No RBA table mapped"),
    ):
        source.fetch_observations(
            series_id="unknown",
            source_code="NOT_A_REAL_CODE",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )

    mock_get.assert_not_called()


def test_fetch_observations_raises_when_no_series_id_row_found() -> None:
    source = RbaSource()

    with (
        patch("httpx.get", return_value=_mock_response(NO_SERIES_ID_ROW_CSV)),
        pytest.raises(RbaConnectorError, match="No 'Series ID' row found"),
    ):
        source.fetch_observations(
            series_id="au_cash_rate",
            source_code="FIRMMCRTD",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )


def test_fetch_observations_raises_when_column_not_found() -> None:
    source = RbaSource()

    with (
        patch("httpx.get", return_value=_mock_response(UNKNOWN_SERIES_CODE_CSV)),
        pytest.raises(RbaConnectorError, match=r"FIRMMCRTD.*not found"),
    ):
        source.fetch_observations(
            series_id="au_cash_rate",
            source_code="FIRMMCRTD",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )


def test_fetch_observations_retries_transient_failure_then_succeeds() -> None:
    fixture = _load_fixture("rba_f1_cash_rate.csv")
    source = RbaSource()

    with (
        patch(
            "httpx.get", side_effect=[httpx.ConnectError("boom"), _mock_response(fixture)]
        ) as mock_get,
        patch("time.sleep") as mock_sleep,
    ):
        observations = source.fetch_observations(
            series_id="au_cash_rate",
            source_code="FIRMMCRTD",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )

    assert mock_get.call_count == 2
    mock_sleep.assert_called_once()
    assert len(observations) == 4


def test_fetch_observations_fails_fast_on_client_error() -> None:
    source = RbaSource()
    error_response = _mock_response("Not Found", status_code=404)

    with (
        patch("httpx.get", return_value=error_response) as mock_get,
        pytest.raises(RbaConnectorError),
    ):
        source.fetch_observations(
            series_id="au_cash_rate",
            source_code="FIRMMCRTD",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )

    mock_get.assert_called_once()


def test_fetch_observations_raises_after_retries_exhausted() -> None:
    source = RbaSource()

    with (
        patch("httpx.get", side_effect=httpx.ConnectError("boom")) as mock_get,
        patch("time.sleep") as mock_sleep,
        pytest.raises(RbaConnectorError),
    ):
        source.fetch_observations(
            series_id="au_cash_rate",
            source_code="FIRMMCRTD",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )

    assert mock_get.call_count == 4
    assert mock_sleep.call_count == 3
