# LLM Usage Standards

## The invariant

**Language models never produce numbers in this repository.**

Every figure that appears in published output — a percentage change, a
spread, a rate, a multiple — is computed in Python from data that has
been fetched, stored, and validated. The model's role is strictly to
narrate figures it is given. It may not calculate, estimate, infer,
interpolate, or restate a number that was not present in its input.

## Why this exists

A single hallucinated figure in a published financial note is enough to
destroy the credibility of the entire project. Enforcing this as a
written rule, rather than trusting a prompt to hold, is the difference
between a demo and a system.

## How it is enforced

This is a mechanical enforcement, not a prompting convention:

1. Every LLM call takes a Pydantic-validated payload of already-computed
   values as its only input.
2. Every LLM call declares a Pydantic response model whose fields are
   prose only — headlines, summaries, bullet points. No numeric fields.
3. Every generated narrative passes a **numeric fidelity check** before
   publication: every numeral appearing in the output text must be
   traceable back to the input payload, within a stated rounding
   tolerance. If any numeral cannot be traced, the run does not publish.
   It fails loudly instead.
4. Temperature is set to 0 for any call whose output will be treated as
   factual.

## What this rules out

- Asking a model to "calculate the change" or "work out the spread."
- Asking a model to summarise a table by restating its numbers from
  memory rather than being handed the table as structured input.
- Any prompt whose correctness depends on the model's arithmetic being
  reliable. It is not assumed to be, regardless of how well it performs
  in casual testing.

When in doubt: if a task involves a number, write a Python function.
