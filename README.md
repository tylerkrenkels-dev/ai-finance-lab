# AI Finance Lab

Applied AI systems for financial research — built by a final-year Finance
and Financial Mathematics student to demonstrate production-grade AI
engineering to employers in investment banking, global markets, quantitative
finance, and venture capital.

[![CI](https://github.com/tylerkrenkels-dev/ai-finance-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/tylerkrenkels-dev/ai-finance-lab/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)

## Live output

**[2026-08-12 note →](https://tylerkrenkels-dev.github.io/ai-finance-lab/notes/2026-08-12/)** · [All notes →](https://tylerkrenkels-dev.github.io/ai-finance-lab/notes/)

Also live: [M&A Comparables →](https://tylerkrenkels-dev.github.io/ai-finance-lab/comps/) · [Equity Snapshots →](https://tylerkrenkels-dev.github.io/ai-finance-lab/equities/)

The pipeline runs unattended every weekday morning (06:30 AEST, GitHub Actions
cron) and has published multiple notes on the real schedule with no manual
intervention. It has also weathered a live incident: on 2026-08-11 the
numeric fidelity guard misread an ISO date as a negative number and, by
design, blocked publication rather than risk a bad figure; the bug was fixed
and the next scheduled run published normally. The 2026-08-12 note above
also shows the staleness-marker behaviour working in production — several
slower-moving source series are flagged stale rather than silently dropped.

## What this is

Small, production-grade AI systems for financial research. Three are live and
running unattended: the **Macro Research Digest** (a daily pre-market macro
note), the **M&A Comparables Reference** (precedent-transaction tables cited to
real SEC filings), and the **Equity Snapshot Generator** (weekly valuation and
profitability snapshots for a fixed watchlist). A tool-calling **Research
Agent** over the three remains planned.

The invariant behind every one: **language models never produce numbers in
this codebase.** Every figure is computed in Python and validated before a
model ever sees it — the model narrates, it does not calculate. See
[LLM Usage Standards](https://tylerkrenkels-dev.github.io/ai-finance-lab/standards/llm-usage/)
for how this is enforced mechanically, not as a prompting convention.

## Systems

| System | What it does | Status |
|---|---|---|
| Macro Research Digest | Automated daily pre-market macro note | live |
| M&A Comparables Reference | Precedent-transaction tables transcribed from real SEC filings, every figure cited | live |
| Equity Snapshot Generator | Weekly valuation & profitability snapshots for a fixed watchlist | live |
| Research Agent | Tool-calling agent orchestrating the systems above | planned |

The original blueprint had a fourth system, *Filings Intelligence* (SEC/ASX
retrieval with risk-factor diffing) as phase 2; it was deprioritised in favour
of the M&A Comparables Reference and Equity Snapshot Generator, which shipped
in its place.

Alongside the automated Systems above, this repo also hosts manual M&A/Financial
Sponsors case studies — see [Case Studies](https://tylerkrenkels-dev.github.io/ai-finance-lab/case-studies/).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
git clone https://github.com/tylerkrenkels-dev/ai-finance-lab.git
cd ai-finance-lab
uv sync

cp .env.example .env
# fill in ANTHROPIC_API_KEY and FRED_API_KEY

uv run pytest -m "not network"              # run the test suite
uv run python -m apps.macro_note.main       # macro note pipeline, for today
uv run python -m apps.equity_snapshot.main  # equity snapshot pipeline, full watchlist
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

- **Macro Research Digest** — automated daily pre-market macro note. *Live*, unattended on a weekday cron.
- **M&A Comparables Reference** — precedent-transaction tables transcribed from real SEC filings, every figure traceable to a cited source. *Live.*
- **Equity Snapshot Generator** — weekly valuation and profitability snapshots for a fixed watchlist. *Live*, on a weekly cron.
- **Research Agent** — a tool-calling agent orchestrating the systems above. *Planned.*

The original blueprint sequenced four phases, with a *Filings Intelligence*
system (SEC/ASX retrieval with year-over-year risk-factor diffing) as phase 2.
That was deprioritised in favour of the M&A Comparables Reference and Equity
Snapshot Generator, which shipped in its place. Each system is still built and
stabilised before the next is started.

## Documentation

Full docs, architecture writeups, and decision records: https://tylerkrenkels-dev.github.io/ai-finance-lab/
