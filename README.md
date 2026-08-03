# AI Finance Lab

Applied AI systems for financial research — built by a final-year Finance
and Financial Mathematics student to demonstrate production-grade AI
engineering to employers in investment banking, global markets, quantitative
finance, and venture capital.

[![CI](https://github.com/tylerkrenkels-dev/ai-finance-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/tylerkrenkels-dev/ai-finance-lab/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)

## Live output

**[Daily Notes →](https://tylerkrenkels-dev.github.io/ai-finance-lab/notes/)**

The pipeline is built, deployed, and scheduled (weekdays, 06:30 AEST). No
note has been published by the actual schedule yet — this section will be
replaced with a screenshot of a real, unattended run once the first one
lands, not the manually-triggered dry run used to prove the pipeline works
end to end.

## What this is

Four small, production-grade AI systems for financial research, built in
strict sequence. The current phase is the **Macro Research Digest** — an
automated daily pre-market macro note, published unattended every weekday.

The invariant behind all four: **language models never produce numbers in
this codebase.** Every figure is computed in Python and validated before a
model ever sees it — the model narrates, it does not calculate. See
[LLM Usage Standards](https://tylerkrenkels-dev.github.io/ai-finance-lab/standards/llm-usage/)
for how this is enforced mechanically, not as a prompting convention.

## Systems

| System | What it does | Status |
|---|---|---|
| Macro Research Digest | Automated daily pre-market macro note | live |
| Filings Intelligence | SEC/ASX retrieval with citations | planned |
| Deal & Comps Platform | Australian precedent transaction database | planned |
| Research Agent | Tool-calling agent orchestrating the above | planned |

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
git clone https://github.com/tylerkrenkels-dev/ai-finance-lab.git
cd ai-finance-lab
uv sync

cp .env.example .env
# fill in ANTHROPIC_API_KEY and FRED_API_KEY

uv run pytest -m "not network"          # run the test suite
uv run python -m apps.macro_note.main   # run the full pipeline once, for today
```

## Architecture

Single monorepo. `apps/` holds one directory per system; `core/` stays empty
until three separate applications demonstrate the same concrete need (the
"rule of three" — see
[ADR-0001](https://tylerkrenkels-dev.github.io/ai-finance-lab/adr/0001-monorepo-with-earned-abstractions/)).
GitHub Actions cron orchestrates; DuckDB over Parquet is the analytics store;
nothing heavier.

Full writeup: [Architecture Overview](https://tylerkrenkels-dev.github.io/ai-finance-lab/architecture/overview/).

## Standards

- [Engineering Standards](https://tylerkrenkels-dev.github.io/ai-finance-lab/standards/engineering/) — branching, commits, PR process, code style
- [Testing Standards](https://tylerkrenkels-dev.github.io/ai-finance-lab/standards/testing/) — what gets a unit test, a cassette, an eval
- [LLM Usage Standards](https://tylerkrenkels-dev.github.io/ai-finance-lab/standards/llm-usage/) — the numeric fidelity invariant, enforced

## Roadmap

1. **Macro Research Digest** — automated daily pre-market macro note (current phase, live)
2. **Filings Intelligence** — SEC and ASX retrieval with citations and year-over-year risk factor diffing
3. **Deal & Comps Platform** — Australian transaction database and precedent comparables
4. **Research Agent** — tool-calling agent orchestrating the three systems above

Built strictly in sequence. After Phase 1's five-day unattended streak, no
new features for thirty days before Phase 2 begins.

## Documentation

Full docs, architecture writeups, and decision records: https://tylerkrenkels-dev.github.io/ai-finance-lab/
