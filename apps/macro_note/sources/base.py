"""The structural contract every data source connector implements."""

from datetime import date
from typing import Protocol, runtime_checkable

from apps.macro_note.models import Observation


@runtime_checkable
class SourceProvider(Protocol):
    """A connector that fetches raw Observations for one series from one source."""

    def fetch_observations(
        self, series_id: str, source_code: str, start: date, end: date
    ) -> list[Observation]:
        """Fetch Observations for `series_id` (queried as `source_code`) over [start, end].

        Args:
            series_id: The registry's canonical series id, e.g. "us_10y".
            source_code: The source-specific ticker to query, e.g. "DGS10".
            start: Inclusive start of the observation date range.
            end: Inclusive end of the observation date range.

        Returns:
            Raw Observations tagged with the canonical `series_id`. No computation.
        """
        ...
