"""Market data connector: fetches raw Observations from yfinance.

Covers gold, copper, and the ASX 200 (the registry's 3 yfinance series). No
computation, per layer discipline.

yfinance is an unofficial, unstable API with no stable exception surface to
whitelist as "retryable" the way FRED/RBA's HTTP status codes are. Unlike
those two connectors, this one never raises: any failure is logged and
reported as an empty list, so the orchestration layer can fall back to the
last stored value and mark the metric stale by date. The distinction between
"genuinely no data for this range" and "yfinance is down" only matters to a
human debugging a stale marker, which the error-level log below covers.
"""

import logging
import math
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import yfinance

from apps.macro_note.models import Observation

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 0.5


class MarketSource:
    """Fetches Observations from yfinance. Implements SourceProvider.

    Never raises. See module docstring for why.
    """

    def fetch_observations(
        self, series_id: str, source_code: str, start: date, end: date
    ) -> list[Observation]:
        """Fetch Observations for `series_id` (queried as `source_code`) over [start, end].

        Returns an empty list if yfinance has nothing for this range, or if every
        retry attempt failed. Never raises.
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self._fetch(series_id, source_code, start, end)
            except Exception as exc:  # yfinance's failures aren't enumerable enough to whitelist
                logger.warning(
                    "yfinance fetch failed for %s (%s) (attempt %d/%d): %s",
                    series_id,
                    source_code,
                    attempt + 1,
                    MAX_RETRIES + 1,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_SECONDS * (2**attempt))

        logger.error(
            "yfinance unavailable for %s (%s) after %d attempts; treating as no data",
            series_id,
            source_code,
            MAX_RETRIES + 1,
        )
        return []

    def _fetch(self, series_id: str, source_code: str, start: date, end: date) -> list[Observation]:
        # yfinance's `end` is exclusive; widen by a day so the requested end date is included.
        history: Any = yfinance.Ticker(source_code).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if history.empty:
            return []

        fetched_at = datetime.now(UTC)
        observations: list[Observation] = []
        for timestamp, row in history.iterrows():
            close = float(row["Close"])
            if math.isnan(close):
                continue
            observations.append(
                Observation(
                    series_id=series_id,
                    value=close,
                    as_of=timestamp.date(),
                    fetched_at=fetched_at,
                )
            )
        return observations
