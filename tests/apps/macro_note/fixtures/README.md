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

## iso_date_facts.json / iso_date_narrative.json

The real `NoteFacts` payload and real narrative from the `macro-note` workflow
run that failed in production on 2026-08-11 (GitHub Actions run
`31536688043`), reconstructed verbatim from the run's logged payloads. The
guard raised `NumericFidelityError` on `bullets[0]`'s `"...from 2026-08-07,
while..."`, flagging `"-07"` as an untraceable `-7.0` -- a false positive: the
date is real and correct, but the digit extractor's sign regex was reading
the date's separator hyphens as minus signs, splitting `2026-08-07` into
`2026`, `-08`, `-07`. See the guard module docstring's ISO-date handling for
the fix.

Use this pair to confirm the fix against the exact real-world case rather
than a synthetic stand-in: the full narrative must trace cleanly against the
full facts payload, with no manual editing of either.
