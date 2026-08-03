import json
from datetime import date
from pathlib import Path

from apps.macro_note.models import Metric, MetricChange, NoteFacts, NoteNarrative, Section
from apps.macro_note.render import note_filename, render_note

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_NO_CHANGE = MetricChange(pct_change=None, bp_change=None, reference_as_of=None)


def _load_fixture_facts() -> NoteFacts:
    raw = json.loads((FIXTURES_DIR / "narrative_smoke_facts.json").read_text())
    return NoteFacts.model_validate(raw)


def _load_fixture_narrative() -> NoteNarrative:
    raw = json.loads((FIXTURES_DIR / "narrative_smoke_narrative.json").read_text())
    return NoteNarrative.model_validate(raw)


def test_note_filename_is_dated() -> None:
    assert note_filename(date(2026, 7, 31)) == "2026-07-31.md"


def test_render_note_includes_front_matter() -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()

    rendered = render_note(facts, narrative)

    assert rendered.startswith("---\n")
    assert 'title: "Macro Research Digest — 2026-07-31"' in rendered
    assert "date: 2026-07-31" in rendered
    assert f'description: "{narrative.headline}"' in rendered
    assert "stale: true" in rendered  # au_cash_rate is stale in this fixture


def test_render_note_includes_headline_summary_and_bullets() -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()

    rendered = render_note(facts, narrative)

    assert f"# {narrative.headline}" in rendered
    assert narrative.summary in rendered
    for bullet in narrative.bullets:
        assert f"- {bullet}" in rendered


def test_render_note_includes_data_warnings_section() -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()

    rendered = render_note(facts, narrative)

    assert "## Data Warnings" in rendered
    assert facts.data_warnings[0] in rendered


def test_render_note_data_warnings_section_omitted_when_empty() -> None:
    facts = _facts_with_metrics(stale=False)
    narrative = NoteNarrative(headline="Steady", summary="No change.", bullets=["No change."])

    rendered = render_note(facts, narrative)

    assert "## Data Warnings" not in rendered


def test_render_note_metrics_table_marks_stale_row_and_not_fresh_row() -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()

    rendered = render_note(facts, narrative)

    assert "| US 10-Year Treasury Yield |" in rendered
    assert "| RBA Cash Rate |" in rendered

    lines = rendered.splitlines()
    us_10y_row = next(line for line in lines if line.startswith("| US 10-Year Treasury Yield |"))
    au_cash_rate_row = next(line for line in lines if line.startswith("| RBA Cash Rate |"))

    assert "**Stale**" not in us_10y_row
    assert us_10y_row.rstrip().endswith("| Fresh |")
    assert "**Stale**" in au_cash_rate_row


def test_render_note_stale_false_and_no_marker_when_nothing_stale() -> None:
    facts = _facts_with_metrics(stale=False)
    narrative = NoteNarrative(headline="Steady", summary="No change.", bullets=["No change."])

    rendered = render_note(facts, narrative)

    assert "stale: false" in rendered
    assert "**Stale**" not in rendered
    assert "| Fresh |" in rendered


def test_render_note_includes_curve_slope_table() -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()

    rendered = render_note(facts, narrative)

    assert "### Curve Slopes" in rendered
    assert "| AU-US 10Y Spread |" in rendered
    assert "-43.0bp" in rendered


def test_render_note_headings_are_separated_by_blank_lines() -> None:
    """A heading immediately following a list/table with no blank line can fail to
    parse under Python-Markdown (what MkDocs uses) -- regression guard for that."""
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()

    rendered = render_note(facts, narrative)

    for heading in ("## Data Warnings", "## Rates", "### Metrics", "### Curve Slopes"):
        index = rendered.index(heading)
        assert rendered[index - 2 : index] == "\n\n", f"no blank line before {heading!r}"


def _facts_with_metrics(*, stale: bool) -> NoteFacts:
    metric = Metric(
        series_id="us_10y",
        label="US 10-Year Treasury Yield",
        value=4.25,
        unit="%",
        as_of=date(2026, 7, 31),
        change_1d=_NO_CHANGE,
        change_1w=_NO_CHANGE,
        change_1m=_NO_CHANGE,
        stale=stale,
        stale_as_of=date(2026, 7, 20) if stale else None,
    )
    return NoteFacts(
        note_date=date(2026, 7, 31), sections=[Section(title="Rates", metrics=[metric])]
    )
