"""FRED connector: fetches raw Observations from the FRED API. No computation."""

import logging
import time
from datetime import UTC, date, datetime
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.macro_note.models import Observation

logger = logging.getLogger(__name__)

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 0.5

# FRED marks non-trading days (weekends, holidays) with this literal instead of a number.
MISSING_VALUE = "."


class FredConnectorError(RuntimeError):
    """Raised when the FRED API cannot be reached or returns an unusable response."""


class FredSettings(BaseSettings):
    """FRED API credentials, read from .env. Never hardcoded."""

    fred_api_key: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class FredSource:
    """Fetches Observations from the FRED API. Implements SourceProvider."""

    def __init__(self, settings: FredSettings | None = None) -> None:
        # mypy sees fred_api_key as a required constructor arg; pydantic-settings
        # actually supplies it from the environment/.env at runtime.
        self._settings = settings or FredSettings()  # type: ignore[call-arg]

    def fetch_observations(
        self, series_id: str, source_code: str, start: date, end: date
    ) -> list[Observation]:
        """Fetch Observations for `series_id` (queried as `source_code`) over [start, end]."""
        raw_observations = self._request_with_retry(source_code, start, end)
        fetched_at = datetime.now(UTC)
        return [
            Observation(
                series_id=series_id,
                value=float(item["value"]),
                as_of=date.fromisoformat(item["date"]),
                fetched_at=fetched_at,
            )
            for item in raw_observations
            if item["value"] != MISSING_VALUE
        ]

    def _request_with_retry(self, source_code: str, start: date, end: date) -> list[dict[str, str]]:
        params = {
            "series_id": source_code,
            "api_key": self._settings.fred_api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = httpx.get(
                    FRED_OBSERVATIONS_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS
                )
                response.raise_for_status()
                # FRED's response schema isn't typed; Observation validates each item below.
                body: Any = response.json()
                raw_observations: list[dict[str, str]] = body["observations"]
                return raw_observations
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise FredConnectorError(
                        f"FRED request for series {source_code!r} failed with "
                        f"HTTP {exc.response.status_code}, not retrying"
                    ) from exc
                last_error = exc
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = exc

            logger.warning(
                "FRED request failed for %s (attempt %d/%d): %s",
                source_code,
                attempt + 1,
                MAX_RETRIES + 1,
                last_error,
            )
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE_SECONDS * (2**attempt))

        raise FredConnectorError(
            f"FRED request for series {source_code!r} failed after {MAX_RETRIES + 1} attempts"
        ) from last_error
