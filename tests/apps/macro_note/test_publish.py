import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from apps.macro_note.models import Metric, MetricChange, NoteFacts, NoteNarrative, Section
from apps.macro_note.publish import publish_note, update_index, write_note
from apps.macro_note.render import render_note

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_NO_CHANGE = MetricChange(pct_change=None, bp_change=None, reference_as_of=None)

_INDEX_TEMPLATE = """# Daily Notes

The Macro Research Digest publishes here every weekday morning once Phase 1
is live. Each note is dated and permanent.

No notes have been published yet — Phase 1 is in progress.

<!-- notes:start -->
<!-- notes:end -->
"""


def _load_fixture_facts() -> NoteFacts:
    raw = json.loads((FIXTURES_DIR / "narrative_smoke_facts.json").read_text())
    return NoteFacts.model_validate(raw)


def _load_fixture_narrative() -> NoteNarrative:
    raw = json.loads((FIXTURES_DIR / "narrative_smoke_narrative.json").read_text())
    return NoteNarrative.model_validate(raw)


def _facts_for(note_date: date) -> NoteFacts:
    metric = Metric(
        series_id="us_10y",
        label="US 10-Year Treasury Yield",
        value=4.25,
        unit="%",
        as_of=note_date,
        change_1d=_NO_CHANGE,
        change_1w=_NO_CHANGE,
        change_1m=_NO_CHANGE,
    )
    return NoteFacts(note_date=note_date, sections=[Section(title="Rates", metrics=[metric])])


@pytest.fixture
def docs_dir(tmp_path: Path) -> Iterator[Path]:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "index.md").write_text(_INDEX_TEMPLATE)
    yield tmp_path


def test_write_note_writes_rendered_content_to_dated_path(docs_dir: Path) -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()
    notes_dir = docs_dir / "notes"

    path = write_note(facts, narrative, notes_dir)

    assert path == notes_dir / "2026-07-31.md"
    assert path.read_text() == render_note(facts, narrative)


def test_write_note_refuses_to_overwrite_by_default(docs_dir: Path) -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()
    notes_dir = docs_dir / "notes"
    write_note(facts, narrative, notes_dir)

    with pytest.raises(FileExistsError):
        write_note(facts, narrative, notes_dir)


def test_write_note_overwrite_true_replaces_existing_file(docs_dir: Path) -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()
    notes_dir = docs_dir / "notes"
    write_note(facts, narrative, notes_dir)

    revised = NoteNarrative(
        headline="Revised Headline", summary=narrative.summary, bullets=narrative.bullets
    )
    path = write_note(facts, revised, notes_dir, overwrite=True)

    assert "Revised Headline" in path.read_text()


def test_update_index_raises_when_markers_missing(tmp_path: Path) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "index.md").write_text("# Daily Notes\n\nNo markers here.\n")

    with pytest.raises(ValueError, match="notes:start"):
        update_index(notes_dir)


def test_publish_note_writes_file_and_updates_index(docs_dir: Path) -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()

    path = publish_note(facts, narrative, docs_dir=docs_dir)

    assert path == docs_dir / "notes" / "2026-07-31.md"
    assert path.exists()

    index_text = (docs_dir / "notes" / "index.md").read_text()
    assert f"[2026-07-31 — {narrative.headline}](2026-07-31.md)" in index_text
    # Hand-authored prose above the markers must survive untouched.
    assert "Each note is dated and permanent." in index_text


def test_publish_note_reruns_are_idempotent_with_overwrite(docs_dir: Path) -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()

    publish_note(facts, narrative, docs_dir=docs_dir, overwrite=True)
    publish_note(facts, narrative, docs_dir=docs_dir, overwrite=True)

    index_text = (docs_dir / "notes" / "index.md").read_text()
    assert index_text.count("2026-07-31.md") == 1


def test_publish_note_second_date_lists_both_most_recent_first(docs_dir: Path) -> None:
    older = _facts_for(date(2026, 7, 30))
    newer = _facts_for(date(2026, 7, 31))
    older_narrative = NoteNarrative(headline="Older Note", summary="s", bullets=["b"])
    newer_narrative = NoteNarrative(headline="Newer Note", summary="s", bullets=["b"])

    publish_note(older, older_narrative, docs_dir=docs_dir)
    publish_note(newer, newer_narrative, docs_dir=docs_dir)

    index_text = (docs_dir / "notes" / "index.md").read_text()
    assert index_text.index("2026-07-31.md") < index_text.index("2026-07-30.md")
