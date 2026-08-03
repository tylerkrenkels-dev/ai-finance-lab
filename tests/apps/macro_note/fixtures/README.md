# Fixtures

## narrative_smoke_facts.json / narrative_smoke_narrative.json

A real `NoteFacts` payload and the real `claude-haiku-4-5` output it produced
(temperature=0, live API call, captured during #19 review) -- not a synthetic
stand-in. `narrative_smoke_narrative.json` contains one fact reported twice in
different number formats: the summary says "last updated two days ago" while
bullet 3 says "last updated 2 days ago", both describing the same
`data_warnings` entry in `narrative_smoke_facts.json`. Both traces are
numerically correct; only the surface form differs.

Use this pair when building #20's numeric fidelity guard: it must accept
"2" and "two" as the same traceable value, because the system prompt's
digit-form instruction is a best-effort nudge that the model does not follow
consistently within a single response (see `apps/macro_note/narrative.py`
module docstring). A guard tested only against clean digit-form output would
pass this fixture's bullets and incorrectly fail its summary.
