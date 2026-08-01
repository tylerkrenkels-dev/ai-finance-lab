"""DuckDB + Parquet backend for persisting Observations.

DuckDB is the live, queryable store: a single on-disk database file with a
PRIMARY KEY-enforced observations table, giving idempotent upsert via
DuckDB's native ON CONFLICT and fast latest()/history() queries. Every
upsert also refreshes a Parquet export of the same table -- that's the
"Parquet on local disk" half of the architecture: a portable,
DuckDB-independent copy of the data any other tool (a notebook, a future
app, `duckdb` from the terminal) can read without going through this class
or this codebase. Reads in this class always come from the DuckDB table,
never the Parquet export; the export is one-way, for external consumption.

See docs/adr/0002-duckdb-over-postgres.md for why DuckDB over Postgres/SQLite.
"""

from pathlib import Path

import duckdb

from apps.macro_note.models import Observation, SeriesSource

DEFAULT_DATA_DIR = Path("data")
DB_FILENAME = "macro_note.duckdb"
PARQUET_FILENAME = "observations.parquet"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS observations (
    series_id  VARCHAR NOT NULL,
    obs_date   DATE NOT NULL,
    source     VARCHAR NOT NULL,
    value      DOUBLE NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (series_id, obs_date, source)
)
"""

_UPSERT_SQL = """
INSERT INTO observations (series_id, obs_date, source, value, fetched_at)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (series_id, obs_date, source)
DO UPDATE SET value = excluded.value, fetched_at = excluded.fetched_at
"""

_SELECT_COLUMNS = "series_id, value, obs_date, fetched_at"


class ObservationStore:
    """DuckDB-backed store for Observations, with a Parquet export for portability."""

    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self._parquet_path = data_dir / PARQUET_FILENAME
        self._conn = duckdb.connect(str(data_dir / DB_FILENAME))
        self._conn.execute(_CREATE_TABLE_SQL)

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def upsert(self, observations: list[Observation], source: SeriesSource) -> None:
        """Insert or update Observations, keyed on (series_id, obs_date, source).

        Re-running the same fetch never creates a duplicate row: an identical
        value is a no-op, a revised value (e.g. a FRED data revision) replaces
        the stored row in place.
        """
        if not observations:
            return
        params = [
            (obs.series_id, obs.as_of, source, obs.value, obs.fetched_at) for obs in observations
        ]
        self._conn.executemany(_UPSERT_SQL, params)
        # DuckDB's COPY target must be a literal, not a bind parameter; escape any
        # single quote defensively even though data_dir is always internally controlled.
        escaped_path = str(self._parquet_path).replace("'", "''")
        self._conn.execute(f"COPY observations TO '{escaped_path}' (FORMAT PARQUET)")

    def latest(self, series_id: str) -> Observation | None:
        """Return the most recently stored Observation for `series_id`, or None."""
        row = self._conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM observations "
            "WHERE series_id = ? ORDER BY obs_date DESC LIMIT 1",
            [series_id],
        ).fetchone()
        if row is None:
            return None
        return Observation(series_id=row[0], value=row[1], as_of=row[2], fetched_at=row[3])

    def history(self, series_id: str, lookback: int) -> list[Observation]:
        """Return the most recent `lookback` Observations for `series_id`, oldest first.

        `lookback` is a count of observations, not a number of calendar days -
        daily series have real gaps (weekends, holidays), so "last 30 stored
        observations" and "last 30 days" are different queries. This returns
        the former.
        """
        rows = self._conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM observations "
            "WHERE series_id = ? ORDER BY obs_date DESC LIMIT ?",
            [series_id, lookback],
        ).fetchall()
        return [
            Observation(series_id=r[0], value=r[1], as_of=r[2], fetched_at=r[3])
            for r in reversed(rows)
        ]
