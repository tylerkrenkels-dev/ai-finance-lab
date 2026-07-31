# Engineering Standards

## Branch strategy

Trunk-based development with short-lived branches.

- `main` is always green and always deployable.
- One branch per logical unit of work, living no longer than a few days.
- Branches are never committed to directly. Every change goes through a
  pull request, gated by CI, and squash-merged.
- Branch names follow `type/short-description`, e.g. `feat/fred-connector`,
  `fix/rba-csv-parsing`, `docs/adr-0002-duckdb`.

## Commit convention

Conventional Commits: `type(scope): imperative summary`.

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `ci`.

Commit bodies explain **why** a change was made, never **what** changed —
the diff already shows what changed.

## Pull request process

- Every PR is gated by the `ci` status check (lint, types, tests).
- Branch protection blocks merging until `ci` passes.
- Squash merge only. The squashed commit title becomes the permanent
  entry in `main`'s history, so it should read well on its own.
- Head branches are deleted automatically after merge.

## The rule of three

`core/` starts empty. A module is extracted into `core/` only once three
separate applications demonstrate the same concrete requirement. Until
then, duplication between `apps/` directories is accepted deliberately.
Abstractions designed before their third real use are usually wrong.

## Code style

- `ruff` decides all formatting and linting. Do not hand-format code that
  disagrees with it.
- Type hints on every function signature. `mypy --strict` applies to
  `core/` and `apps/`.
- Functions stay under roughly 50 lines; modules under roughly 300.
- Pydantic models sit at every layer boundary. Plain dicts are fine
  inside a single function, never across a boundary.
- No bare `except:`. Catch specific exceptions with context.
- No `print()` in library code — use `logging`.

## Project reviews

Once a month, review the roadmap against reality: what shipped, what's
stale, what should be deleted. Deleting a project is a legitimate
outcome and should be expected occasionally.
