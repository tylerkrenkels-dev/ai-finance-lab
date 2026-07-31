# ADR-0001: Monorepo with earned abstractions

**Status:** Accepted
**Date:** 2026-07-31

## Context

This lab consists of four planned systems (Macro Research Digest, Filings
Intelligence, Deal & Comps Platform, Research Agent), built by a solo
developer over roughly six to twelve months, alongside full-time study and
elite athletic training. Available development time is limited to a few
hours per week. The systems are related — they will eventually share data
access patterns, LLM calling conventions, and validation logic — but only
one system exists at the start.

## Decision

Use a single repository (`ai-finance-lab`) containing all systems, rather
than a separate repository per system or a GitHub organisation. Within it,
`apps/` holds one directory per system, and `core/` holds shared modules.

`core/` starts empty. A module is extracted into it only once **three**
separate applications independently need the same functionality — not
before. Until the third real need appears, duplication between apps is
accepted as the correct state, not a defect to be pre-emptively solved.

## Consequences

**Easier:** one CI pipeline, one dependency lockfile, one documentation
site, one commit history that reads as a coherent build log rather than
four disconnected efforts. A reviewer sees one system, not four half
efforts. Refactoring across systems (when it eventually happens) is a
single-repo operation, not a cross-repo coordination problem.

**Harder:** early on, some code will be duplicated between `apps/macro_note`
and whatever the second system turns out to be, before `core/` exists to
hold it. This is accepted deliberately — it is cheaper to tolerate
duplication for a few months than to guess at the wrong abstraction now
and have to unwind it later, which is the more common and more expensive
failure mode for a solo, time-constrained developer.

**Risk accepted knowingly:** if the systems turn out to be far less
similar than expected, the monorepo structure and the rule-of-three
discipline will have cost little, since `core/` was never populated on
spec in the first place.

## Alternatives considered

**Multi-repo (one repository per system).** Rejected. For a solo developer,
this means four separate CI configurations to maintain, four separate
dependency lockfiles that can drift out of sync with each other, and a
portfolio that reads to a reviewer as four thin, disconnected projects
rather than one coherent system. The coordination overhead of keeping
four repositories consistent is not justified until there is a team, or
until a system genuinely needs independent deployment.

**GitHub organisation with one repo per system.** Rejected for the same
reasons as multi-repo, with the added overhead of managing an
organisation for a single-person project. Revisit only if a system needs
to be deployed, licensed, or open-sourced independently of the others.

**Shared `core/` library populated upfront, before any application
exists.** Rejected. Designing shared abstractions before a second (let
alone third) concrete use case exists means guessing at the right shape
of the abstraction. Abstractions designed this way are reliably wrong,
because the actual requirements are not yet known. The rule of three
exists specifically to prevent this failure mode.
