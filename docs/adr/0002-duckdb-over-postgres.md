# ADR-0002: DuckDB over Postgres

**Status:** Accepted
**Date:** 2026-08-01

## Context

CLAUDE.md named DuckDB over Parquet files as the analytics store from the
start of the project, but deferred the reasoning to the point where a real
persistence requirement existed to reason about. That point is now: the
Macro Research Digest has three working connectors (FRED, RBA, a yfinance
wrapper) that each produce `Observation`s on their own schedule, with
genuinely different failure shapes (FRED and RBA fail loud with a typed
exception; the market connector never raises and signals "unavailable" as
an empty list). All three need a common place to land so that a fetch can
be re-run without duplicating data, and so a future orchestration layer can
ask "what's the last known value for this series" when a source fails.

The operating context has not changed since ADR-0001: one developer,
part-time hours, a GitHub Actions cron as the only scheduler, and — the
concrete fact that matters most for this decision — exactly one writer.
The daily digest run is a single sequential process; nothing else writes
to this store concurrently, and nothing ever will under the current
architecture. There is no application server, no request-handling process
that would need a second connection into the same database while the cron
job runs.

## Decision

Persist `Observation`s in a single DuckDB database file
(`data/macro_note.duckdb`) containing one table, keyed on
`(series_id, obs_date, source)`. Idempotent upsert is DuckDB's native
`INSERT ... ON CONFLICT ... DO UPDATE`, not hand-rolled merge logic.

Every write also re-exports the full table to `data/observations.parquet`
via DuckDB's `COPY ... TO ... (FORMAT PARQUET)`. That Parquet file is the
"Parquet files on local disk" half of the original architecture line: a
portable, DuckDB-independent copy that any other tool — a `notebooks/`
exploration, a future app in this same repo, or just `duckdb` from a
terminal — can read directly, without this codebase or a running instance
of `ObservationStore` involved at all. The application itself never reads
the Parquet file back; it is one-way output, not a second source of truth.

## Consequences

**Easier:** upsert, the single hardest part of "never create duplicates
on re-run," is a single SQL statement with a `PRIMARY KEY` doing the
enforcement, rather than application code reading, deduplicating, and
rewriting files by hand. `latest()` and `history()` are plain indexed SQL
queries. There is no server process to start, configure, monitor, or keep
patched — `ObservationStore` opens a file and closes it, which is the
entire operational surface. Backing up or inspecting the data is copying
one `.duckdb` file and one `.parquet` file; either can be opened cold, with
no schema migration tool and no running service, by anyone with a Python
shell.

**Harder:** DuckDB's file format allows exactly one writer at a time. If a
second application in this monorepo ever needs to write to the same store
concurrently — not read, write — this design stops working and something
with real concurrent-write support would be needed. That is treated as
acceptable, not overlooked: nothing in the current or near-term roadmap
introduces a second writer, and per the rule of three, building for
concurrent writes before a second writer exists would be the exact
mistake ADR-0001 already argued against.

**Risk accepted knowingly:** a single `.duckdb` file is a single point of
failure with no replication. For a personal research tool re-derivable
from public data sources (FRED, RBA, Yahoo Finance all retain history),
losing the file costs a backfill, not a business, so this is judged an
acceptable risk rather than one requiring redundancy.

## Alternatives considered

**Postgres.** Rejected. Postgres is a server: a process to run, a port to
open, a version to patch, credentials to manage. None of that buys
anything here — there is no concurrent access to serve and no other
consumer that needs to reach the data over a network. Running a database
server to serve a single-writer, single-reader daily batch job is the
exact kind of infrastructure CLAUDE.md rules out on principle (§8: no
Postgres, no Docker), not just on cost.

**SQLite.** A closer call than Postgres, and a real contender: also a
single embedded file, also zero-operations. Rejected specifically because
this data is analytical, not transactional — the queries this store exists
to serve (`latest()`, `history()` over a lookback window, and future
period-over-period calculations) are columnar scans and aggregations over
a time series, which is DuckDB's design center. SQLite is optimized for
row-oriented reads and writes of individual records, not for this shape of
query, and has no native Parquet support — reading or writing Parquet from
SQLite would mean adding a separate library, whereas DuckDB does both
natively in the same engine already chosen for querying.

**Parquet files with no database at all.** Rejected. This was seriously
considered, since Parquet alone would satisfy "local disk, no server."
The problem is upsert: Parquet files have no row-level update or a native
uniqueness constraint, so idempotent re-runs would require reading the
existing file, deduplicating in application code, and rewriting the whole
file on every single fetch — reinventing, by hand, exactly what a
`PRIMARY KEY` and `ON CONFLICT` already do for free. DuckDB gives that
guarantee natively while still producing a Parquet file as output, so
there was no real tradeoff being given up by keeping DuckDB in the loop.
