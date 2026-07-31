"""RBA connector: fetches raw Observations from RBA statistical table CSVs.

No computation, per layer discipline. RBA doesn't support server-side date
filtering, so the whole table is fetched and the date range is applied after
parsing.
"""

import csv
import io
import logging
import time
from datetime import UTC, date, datetime

import httpx

from apps.macro_note.models import Observation

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 0.5

SERIES_ID_ROW_LABEL = "Series ID"
DATE_FORMAT = "%d-%b-%Y"

# RBA doesn't expose a lookup API for which table holds which series, so this is
# hand-maintained. If a new RBA series is added to the registry, add its table
# URL here too, or fetch_observations will fail loudly rather than guess.
TABLE_URLS: dict[str, str] = {
    "FIRMMCRTD": "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv",
    "FCMYGBAG3D": "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv",
    "FCMYGBAG10D": "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv",
}


class RbaConnectorError(RuntimeError):
    """Raised when an RBA table can't be fetched or its expected shape isn't found."""


class RbaSource:
    """Fetches Observations from RBA statistical table CSVs. Implements SourceProvider."""

    def fetch_observations(
        self, series_id: str, source_code: str, start: date, end: date
    ) -> list[Observation]:
        """Fetch Observations for `series_id` (queried as `source_code`) over [start, end]."""
        table_url = TABLE_URLS.get(source_code)
        if table_url is None:
            raise RbaConnectorError(
                f"No RBA table mapped for source_code {source_code!r}. "
                f"Known source codes: {sorted(TABLE_URLS)}"
            )
        csv_text = self._request_with_retry(table_url)
        return self._parse_observations(csv_text, series_id, source_code, table_url, start, end)

    def _request_with_retry(self, table_url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = httpx.get(table_url, timeout=REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                return response.text
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise RbaConnectorError(
                        f"RBA request for {table_url!r} failed with "
                        f"HTTP {exc.response.status_code}, not retrying"
                    ) from exc
                last_error = exc
            except httpx.HTTPError as exc:
                last_error = exc

            logger.warning(
                "RBA request failed for %s (attempt %d/%d): %s",
                table_url,
                attempt + 1,
                MAX_RETRIES + 1,
                last_error,
            )
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE_SECONDS * (2**attempt))

        raise RbaConnectorError(
            f"RBA request for {table_url!r} failed after {MAX_RETRIES + 1} attempts"
        ) from last_error

    def _find_data_start_and_column(
        self, rows: list[list[str]], table_url: str, source_code: str
    ) -> tuple[int, int]:
        for row_index, row in enumerate(rows):
            if row and row[0].strip() == SERIES_ID_ROW_LABEL:
                try:
                    column_index = row.index(source_code)
                except ValueError as exc:
                    raise RbaConnectorError(
                        f"Series ID {source_code!r} not found in {table_url!r}. "
                        f"Available series IDs: {row[1:]}"
                    ) from exc
                return row_index + 1, column_index
        raise RbaConnectorError(f"No {SERIES_ID_ROW_LABEL!r} row found in {table_url!r}")

    def _parse_observations(
        self,
        csv_text: str,
        series_id: str,
        source_code: str,
        table_url: str,
        start: date,
        end: date,
    ) -> list[Observation]:
        rows = list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))
        data_start, column_index = self._find_data_start_and_column(rows, table_url, source_code)

        fetched_at = datetime.now(UTC)
        observations: list[Observation] = []
        for row in rows[data_start:]:
            if not row or not row[0].strip():
                continue
            try:
                as_of = datetime.strptime(row[0].strip(), DATE_FORMAT).date()
            except ValueError:
                continue
            if not (start <= as_of <= end):
                continue

            value = row[column_index].strip() if column_index < len(row) else ""
            if not value:
                continue
            try:
                observations.append(
                    Observation(
                        series_id=series_id, value=float(value), as_of=as_of, fetched_at=fetched_at
                    )
                )
            except ValueError as exc:
                raise RbaConnectorError(
                    f"Unparseable value {value!r} for {source_code!r} on {as_of} in {table_url!r}"
                ) from exc

        return observations
