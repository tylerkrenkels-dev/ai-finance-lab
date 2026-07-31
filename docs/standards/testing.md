# Testing Standards

## What gets a unit test

Every function in a `calculations/` module has a unit test with a
**hand-computed** expected value. If the expected value was derived by
running the code itself, the test proves nothing.

## What gets a cassette

Any test that would otherwise make a real network call is either:

- marked `@pytest.mark.network` and excluded from CI, or
- backed by a recorded fixture/cassette, so the test is deterministic
  and does not depend on a third-party API being reachable.

CI never depends on an external service being up. This is enforced by
running `pytest -m "not network"` in the `ci` workflow.

## What gets an eval

Generative features (anything that calls an LLM) are not considered
tested by a unit test alone. They require an eval: a small, hand-labelled
dataset with a scoring function, run and reported on explicitly, not
just checked for "did it not crash."

## Coverage targets

- `core/`: 90% once populated.
- `calculations/` modules specifically: 90%, since these carry the
  numbers that end up in published output.
- `apps/` generally: no fixed target — coverage on glue code and I/O is
  less meaningful than coverage on pure logic.

## The rule that is never broken

A failing test is never weakened or deleted to make CI pass. If a test
fails, either the code is wrong or the test's expectation was wrong —
and if it's the latter, that's stated explicitly in the commit message,
not silently patched away.
