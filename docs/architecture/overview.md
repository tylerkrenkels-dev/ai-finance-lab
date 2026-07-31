# Architecture Overview

## Repository

Single monorepo. `apps/` holds one directory per system. `core/` holds
shared modules, populated only once three applications demonstrate the
same concrete requirement (see [ADR-0001](../adr/0001-monorepo-with-earned-abstractions.md)).
## The core invariant

Language models never produce numbers in this repository. Every figure is
computed in Python and validated before a model ever sees it; the model
narrates, it does not calculate. See
[LLM Usage Standards](../standards/llm-usage.md) for how this is enforced.
