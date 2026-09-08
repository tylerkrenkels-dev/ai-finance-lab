# Research Agent

The fourth system. A local, interactive agent that answers a research question by
reading the **published output of the other three systems** and returning an
answer in which every claim cites a real source — and every citation is
mechanically verified against that specific source before you see it.

It is deliberately **not** a hosted service, a chat interface, an API, or a
scheduled job. There is no cron, no `docs/` archive of its answers, no public
endpoint. You run it from a terminal, one question at a time. Hosting,
rate-limiting and public cost exposure are a separate, larger project that is out
of scope.

## Running it

    uv run python -m apps.research_agent "How do Apple and Microsoft compare on profitability and valuation?"

- The answer is printed to stdout. Exit status is `0` for an answer (full or
  partial) and `1` for a refusal.
- `--transcript` prints the full run trace to stderr: the tool calls in order,
  each draft, and the guard result for each.
- `--docs-dir PATH` points the agent at a different published-docs root
  (default `docs/`).
- Requires `ANTHROPIC_API_KEY` in `.env`, like the other systems.

## How it works

1. **Discovery.** Python lists every published source across the three systems —
   reading front matter only — and puts that manifest in the prompt. Around
   thirty sources. No vector store, no retrieval layer; the model picks from a
   list.
2. **Retrieval.** The model calls `read_macro_note`, `read_equity_snapshot`, or
   `read_comp_table` for the pages it needs. Each returns that page's
   already-computed, already-validated structured figures. The loop ends when the
   model stops calling tools.
3. **Generation.** The model returns a list of claims. Each claim is one
   assertion with exactly one citation — a source id, or `none` for connective
   prose that contains no figure.
4. **The citation guard** — the part that makes the output trustworthy. Two
   mechanical checks run over the claims:
     - **Per-citation numeric fidelity.** Every number in a claim must appear,
       with the same value and unit, in the figure set of *that claim's own cited
       page* — not the union of everything retrieved. A union check would pass a
       real figure attributed to the wrong page, because the number is real
       *somewhere*. Per-citation catches the misattribution.
     - **Comparison constraint.** A claim that states a change, a trend, or a
       magnitude comparison is allowed only when the cited page itself publishes
       that as a labelled quantity — a macro note's own 1-day / 1-week / 1-month
       delta. Equity snapshots and comps tables have no time dimension, so any
       "rose", "higher", or "compared to" about their figures is model arithmetic
       and is rejected.

   When a claim fails, the guard's specific finding is fed back and the model
   gets **one** retry. Claims that still fail are withheld; if fewer than half
   survive, the agent refuses and names the sources it consulted. A failing draft
   is never shown.

## Example: the first live run

Unedited, from the agent's first run against the live API and the committed
pages. The equity pages are refreshed in place each week, so the figures below
are from the 2026-09-04 snapshots and will not match the current pages — the
mechanism is the point, not the values.

**Question**

> How do Apple and Microsoft compare on profitability and valuation?

**Sources the model chose to read**

    1. read_equity_snapshot({'ticker': 'AAPL'}) -> equity_snapshot/AAPL
    2. read_equity_snapshot({'ticker': 'MSFT'}) -> equity_snapshot/MSFT

**First answer.** The model wrote seven claims, each folding an Apple figure and
a Microsoft figure into one sentence under a single citation:

    {
      "question": "How do Apple and Microsoft compare on profitability and valuation?",
      "claims": [
        { "text": "Apple's trailing P/E is 36.65x, while Microsoft's trailing P/E is 28.41x.", "citation": "equity_snapshot/AAPL" },
        { "text": "Apple's forward P/E is 33.42x, while Microsoft's forward P/E is 21.20x.", "citation": "equity_snapshot/AAPL" },
        { "text": "Apple's EV/EBITDA is 27.93x, while Microsoft's EV/EBITDA is 19.37x.", "citation": "equity_snapshot/AAPL" },
        { "text": "Microsoft has a gross margin of 67.94%, compared to Apple's gross margin of 48.65%.", "citation": "equity_snapshot/MSFT" },
        { "text": "Microsoft has an operating margin of 45.11%, compared to Apple's operating margin of 32.62%.", "citation": "equity_snapshot/MSFT" },
        { "text": "Microsoft has a profit margin of 40.30%, compared to Apple's profit margin of 27.62%.", "citation": "equity_snapshot/MSFT" },
        { "text": "Apple's return on equity is 148.75%, while Microsoft's return on equity is 34.04%.", "citation": "equity_snapshot/AAPL" }
      ]
    }

Take the last claim. `148.75%` is Apple's return on equity and is on the cited
page. `34.04%` is Microsoft's — a real figure, correctly transcribed, but it
lives on a different page.

**Guard result: FAIL** — ten violations across the seven claims:

    guard FAIL -- claim 1 figure_not_in_citation; claim 2 figure_not_in_citation; claim 3 figure_not_in_citation; claim 4 figure_not_in_citation; claim 4 unbacked_relation; claim 5 figure_not_in_citation; claim 5 unbacked_relation; claim 6 figure_not_in_citation; claim 6 unbacked_relation; claim 7 figure_not_in_citation

The `--transcript` flag logs that verdict line. Each violation also carries a
full explanation, which the loop feeds back to the model. For claim 7:

> The figure "34.04%" is cited to equity_snapshot/AAPL, which does not contain
> it; it appears in equity_snapshot/MSFT. Cite the source the claim describes, or
> split the sentence so each figure is cited to its own source.
> equity_snapshot/AAPL reports these percentages: 148.75%, 27.62%, 32.62%,
> 48.65%.

A check against everything retrieved this run would have passed that claim —
`34.04%` *is* a figure the agent read — so only the per-citation check sees that
it is pinned to the wrong page. Claims 1–6 fail the same way (each compound
sentence carries one figure that lives on the other page). Claims 4–6 also draw
an `unbacked_relation`:

> Claim 4 asserts a change or comparison ("compared to Apple's gross margin of
> 48.65%."); Equity snapshots carry no figures over time, so state only the level
> each source reports, each as its own claim.

**The retry.** The findings were fed back. The model split every compound claim
in two, each cited to its own page, and dropped the comparatives — for the
return-on-equity claim:

    { "text": "Apple's return on equity is 148.75%.",    "citation": "equity_snapshot/AAPL" }
    { "text": "Microsoft's return on equity is 34.04%.", "citation": "equity_snapshot/MSFT" }

**Guard result on the retry: PASS.** Final output, exit 0 (the body is a single
paragraph):

    Apple's trailing P/E is 36.65x. [1] Microsoft's trailing P/E is 28.41x. [2] Apple's forward P/E is 33.42x. [1] Microsoft's forward P/E is 21.20x. [2] Apple's EV/EBITDA is 27.93x. [1] Microsoft's EV/EBITDA is 19.37x. [2] Apple's gross margin is 48.65%. [1] Microsoft's gross margin is 67.94%. [2] Apple's operating margin is 32.62%. [1] Microsoft's operating margin is 45.11%. [2] Apple's profit margin is 27.62%. [1] Microsoft's profit margin is 40.30%. [2] Apple's return on equity is 148.75%. [1] Microsoft's return on equity is 34.04%. [2]

    References
    [1] equity_snapshot/AAPL — docs/equities/aapl.md
    [2] equity_snapshot/MSFT — docs/equities/msft.md

## Status

Built and merged in PR #99. Local and interactive only — proven on live runs, not
run on a schedule.
