# AI Finance Lab

Applied AI systems for financial research, built by a final-year Finance and
Financial Mathematics student.

This site is both the engineering documentation for the lab and the public
archive of its automated output.

## Systems

| System | What it does | Status |
|---|---|---|
| [Macro Research Digest](notes/index.md) | Automated daily pre-market macro note | live |
| [M&A Comparables Reference](comps/index.md) | Precedent-transaction tables transcribed from real SEC filings, every figure cited | live |
| [Equity Snapshot Generator](equities/index.md) | Weekly valuation & profitability snapshots for a fixed watchlist | live |
| [Research Agent](research-agent/index.md) | Tool-calling agent orchestrating the systems above | live |

The original blueprint had a fourth system, *Filings Intelligence* (SEC/ASX
retrieval with risk-factor diffing) as phase 2; it was deprioritised in favour
of the M&A Comparables Reference and Equity Snapshot Generator, which shipped
in its place.

See [Architecture](architecture/overview.md) for how the systems are built,
and [Decisions](adr/index.md) for why.
