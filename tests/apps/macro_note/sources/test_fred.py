import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from apps.macro_note.models import Observation
from apps.macro_note.sources.base import SourceProvider
from apps.macro_note.sources.fred import FredConnectorError, FredSettings, FredSource

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _settings() -> FredSettings:
    return FredSettings(fred_api_key="test-key")


def _load_fixture(name: str) -> dict[str, object]:
    fixture: dict[str, object] = json.loads((FIXTURES_DIR / name).read_text())
    return fixture


def _mock_response(json_body: dict[str, object], status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code, json=json_body, request=httpx.Request("GET", "https://example.com")
    )


def test_fred_source_implements_source_provider() -> None:
    assert isinstance(FredSource(settings=_settings()), SourceProvider)


def test_fetch_observations_filters_missing_values() -> None:
    fixture = _load_fixture("fred_dgs10_observations.json")
    source = FredSource(settings=_settings())

    with patch("httpx.get", return_value=_mock_response(fixture)) as mock_get:
        observations = source.fetch_observations(
            series_id="us_10y",
            source_code="DGS10",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )

    mock_get.assert_called_once()
    assert len(observations) == 4
    assert all(isinstance(obs, Observation) for obs in observations)
    assert all(obs.series_id == "us_10y" for obs in observations)
    assert observations[0].as_of == date(2026, 7, 28)
    assert observations[0].value == 4.21


def test_fetch_observations_retries_transient_failure_then_succeeds() -> None:
    fixture = _load_fixture("fred_dgs10_observations.json")
    source = FredSource(settings=_settings())

    with (
        patch(
            "httpx.get", side_effect=[httpx.ConnectError("boom"), _mock_response(fixture)]
        ) as mock_get,
        patch("time.sleep") as mock_sleep,
    ):
        observations = source.fetch_observations(
            series_id="us_10y",
            source_code="DGS10",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )

    assert mock_get.call_count == 2
    mock_sleep.assert_called_once()
    assert len(observations) == 4


def test_fetch_observations_fails_fast_on_client_error() -> None:
    source = FredSource(settings=_settings())
    error_response = _mock_response(
        {"error_message": "Bad Request. Invalid api_key."}, status_code=400
    )

    with (
        patch("httpx.get", return_value=error_response) as mock_get,
        pytest.raises(FredConnectorError),
    ):
        source.fetch_observations(
            series_id="us_10y",
            source_code="DGS10",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )

    mock_get.assert_called_once()


def test_fetch_observations_raises_after_retries_exhausted() -> None:
    source = FredSource(settings=_settings())

    with (
        patch("httpx.get", side_effect=httpx.ConnectError("boom")) as mock_get,
        patch("time.sleep") as mock_sleep,
        pytest.raises(FredConnectorError),
    ):
        source.fetch_observations(
            series_id="us_10y",
            source_code="DGS10",
            start=date(2026, 7, 27),
            end=date(2026, 7, 31),
        )

    assert mock_get.call_count == 4
    assert mock_sleep.call_count == 3
