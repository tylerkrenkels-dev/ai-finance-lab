# CLAUDE.md — AI Finance Lab

Operating instructions for Claude Code in this repository. Read this fully at the start of every session before proposing any change.

---

## 1. Mission

This repository is the **AI Finance Lab**: a small set of production-grade AI systems for financial research, built by a final-year Finance and Financial Mathematics student to demonstrate applied AI engineering to employers in investment banking, global markets, quantitative finance and venture capital.

Four systems, built strictly in sequence:

1. **Macro Research Digest** — automated daily pre-market macro note, published to GitHub Pages *(current phase)*
2. **Filings Intelligence** — SEC and ASX retrieval with citations and year-over-year risk factor diffing *(not started)*
3. **Deal & Comps Platform** — Australian transaction database and precedent comparables *(not started)*
4. **Research Agent** — tool-calling agent orchestrating the three systems above *(not started)*

**The success criterion is not lines of code. It is a system that runs unattended every weekday for months, and code the owner can explain to an interviewer without notes.** Optimise every decision for those two things.

---

## 2. The invariant — read this twice

**Language models never produce numbers in this repository.**

Python computes every figure. The model receives already-computed, validated values and writes prose about them. The model may not calculate, estimate, infer, interpolate, or restate a figure that is not in its input payload.

This is enforced mechanically, not by prompt:

- Every LLM call takes a Pydantic-validated payload of computed metrics as input.
- Every LLM call declares a Pydantic response model containing only prose fields.
- Every generated narrative passes a **numeric fidelity check** before publication: every numeral in the output must be traceable to the input payload. If it is not, the run fails and publishes nothing.
- Temperature is 0 for anything factual.

If you are ever about to write a prompt that asks a model to compute, compare magnitudes, or work out a change, **stop and write a Python function instead.** A single hallucinated figure in a published note destroys the credibility of the entire project.

---

## 3. Architecture decisions — closed

These are decided. Do not propose alternatives, do not re-litigate, do not "improve" them mid-task. If you believe one is genuinely wrong, say so in one sentence and continue with the decided approach unless the owner overrules.

| Area | Decision |
|---|---|
| Repository | Single monorepo, `apps/` and `core/` |
| Python | 3.12, managed by `uv`. Never `pip`, `poetry`, or `conda` |
| Data contracts | Pydantic v2 at every layer boundary |
| Config and secrets | `pydantic-settings` reading `.env`. Never hardcoded, never committed |
| Analytics store | DuckDB over Parquet files on local disk |
| LLM access | Anthropic SDK called directly, behind a thin local wrapper |
| Lint and format | `ruff` only |
| Types | `mypy`, strict on `core/` and `apps/` |
| Tests | `pytest`. Network tests marked `network` and excluded from CI |
| Orchestration | GitHub Actions cron. Nothing heavier |
| Docs | MkDocs Material to GitHub Pages |

### The rule of three

`core/` is **empty by design**. Shared modules are extracted only when **three** applications demonstrate the same concrete need. Until then, duplication between apps is correct and accepted.

Do not create `core/data/`, `core/llm/`, `core/eval/`, or any other shared module unless explicitly instructed. Abstractions designed before their third use are always wrong.

---

## 4. Layer discipline (current phase: `apps/macro_note/`)

Dependencies flow one way only.

A connector that computes a percentage change is a bug. A calculation function that makes a network call is a bug. Keep the layers clean; it is what makes the whole thing testable.

### Resilience requirement

The daily run must **never fail because one data source failed.** On a source error, fall back to the last stored value and mark the metric stale with its as-of date, visibly, in the published output. A note with a stale marker is a professional output. A missing note breaks the streak, and the streak is the portfolio.

The one exception: if the numeric fidelity guard fails, publish nothing and exit non-zero.

---

## 5. Coding standards

- Type hints on every function signature. No bare `Any` without a comment explaining why.
- Functions under 50 lines. Modules under 300.
- Pydantic models at layer boundaries. Plain dicts only inside a single function.
- Line length 100. `ruff` decides all formatting; never argue with it.
- Docstrings on public functions: one line on purpose, then Args and Returns if non-obvious.
- Explicit errors. No bare `except:`. Catch specific exceptions and log with context.
- No `print()` in library code. Use `logging`.
- Every network call has a timeout and bounded retries with backoff.
- No new dependency without asking first. Justify it against the standard library.
- `notebooks/` is for exploration only and is never imported by application code.

## 6. Testing standards

- Every function in `calculations/` has unit tests with **hand-computed** expected values.
- Network-touching tests are marked `@pytest.mark.network` and excluded from CI.
- Integration tests against external APIs use recorded fixtures or cassettes, never live calls.
- The guard module has a test that feeds it a deliberately fabricated figure and asserts the guard blocks.
- Coverage target: 90% on `calculations/`, 70% on `core/`, no target elsewhere.
- **Never weaken or delete a test to make CI pass.** If a test fails, either the code is wrong or the test was wrong for a reason you can articulate. Say which, and say why.

## 7. Git standards

- Conventional Commits: `type(scope): imperative summary`. Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `ci`.
- Commit bodies explain **why**, never what.
- One branch per issue, named `feat/…`, `fix/…`, `docs/…`, `test/…`, `chore/…`.
- Never commit to `main`. Never force push.
- Never commit `.env`, API keys, `data/`, or `.venv/`.
- **You do not run `git commit`.** Stage nothing. The owner reviews the diff and commits. His name goes on the history, so he reads every line first.

---

## 8. Do not

- Do not install or use **LangChain, LlamaIndex, or any agent framework.** They abstract away exactly what this project exists to learn, churn constantly, and read as tutorial-following to technical interviewers. Raw Anthropic SDK plus Pydantic.
- Do not introduce Postgres, Docker, Kubernetes, Airflow, Prefect, Redis, Celery, or a message queue. DuckDB and GitHub Actions cron are sufficient and deliberate.
- Do not use a hosted vector database. Local only, and not until Phase 2.
- Do not create directories or files for phases that have not started.
- Do not populate `core/` before the rule of three is satisfied.
- Do not ask an LLM to compute, compare, or estimate anything numeric.
- Do not add a web UI, a chat interface, charts, or email delivery to the Macro Digest MVP. They are explicitly out of scope.
- Do not refactor code outside the scope of the current issue, however tempting.
- Do not weaken tests, lower coverage thresholds, or add `# type: ignore` to silence mypy without explaining the specific reason inline.
- Do not add "just in case" configuration, plugin systems, or abstract base classes with one implementation.
- Do not generate code the owner will not be able to explain. When a simple implementation and a clever one both work, choose the simple one.

---

## 9. Session protocol

Every session follows this sequence:

1. **Confirm scope.** Restate the issue and its acceptance criteria in one or two sentences.
2. **Plan first.** List the files you will create or modify and why, *before* writing anything. Wait for approval.
3. **Tests first** for anything in `calculations/` or `guards.py`. Ask the owner for the expected values rather than deriving them yourself.
4. **Implement** the smallest thing that satisfies the acceptance criteria.
5. **Verify:** run `uv run ruff check .`, `uv run ruff format .`, `uv run mypy core apps`, `uv run pytest -m "not network"`. Report the actual output.
6. **Hand back.** Summarise the diff, flag anything you were unsure about, and propose a commit message. Do not commit.

If a task would require touching files outside the stated scope, stop and say so instead of proceeding.

If something in this file conflicts with an instruction in the session, follow the session instruction and say clearly which rule you are departing from and why.

---

## 10. Current state

**Phase:** 1 — Macro Research Digest MVP
**Definition of done:** five consecutive weekday notes published with zero manual intervention, every figure traceable to a named source series, the numeric guard proven to block a fabricated figure, and a simulated source outage handled with a visible staleness marker.
**After that:** no new features for thirty days. Let it run.
