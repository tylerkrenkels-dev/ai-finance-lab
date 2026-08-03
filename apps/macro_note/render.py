"""Renders a NoteFacts + NoteNarrative pair into the published markdown note.

Pure text transformation -- no file I/O. render_note() returns markdown text;
note_filename() returns the canonical dated filename it should be published
under (docs/notes/<note_filename(note_date)>). Actually writing that file is
an orchestration concern, not a rendering one, and belongs to a future issue.
"""

from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from apps.macro_note.models import Metric, MetricChange, NoteFacts, NoteNarrative

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "note.md.j2"

# autoescape is off: this renders markdown/plain text, not HTML, so there is no
# XSS surface -- and HTML-escaping narrative prose would corrupt it (e.g. turning
# an apostrophe into "&#39;").
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_note(facts: NoteFacts, narrative: NoteNarrative) -> str:
    """Render `facts` and `narrative` into the published markdown note text."""
    template = _env.get_template(_TEMPLATE_NAME)
    return template.render(
        facts=facts,
        narrative=narrative,
        any_stale=_any_stale(facts),
    )


def note_filename(note_date: date) -> str:
    """Canonical filename for a note, e.g. "2026-07-31.md" -- lives under docs/notes/."""
    return f"{note_date.isoformat()}.md"


def _any_stale(facts: NoteFacts) -> bool:
    return any(metric.stale for section in facts.sections for metric in section.metrics)


def _format_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%"


def _format_bp(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.1f}bp"


def _format_date(value: date | None) -> str:
    if value is None:
        return "—"
    return value.isoformat()


def _format_value(metric: Metric) -> str:
    if metric.unit == "%":
        return f"{metric.value:.2f}%"
    return f"{metric.value:,.4f} {metric.unit}"


def _format_change(change: MetricChange) -> str:
    if change.bp_change is None:
        return "—"
    bp_text = _format_bp(change.bp_change)
    if change.pct_change is None:
        return bp_text
    return f"{bp_text} / {_format_pct(change.pct_change)}"


_FILTERS: dict[str, Any] = {
    "format_pct": _format_pct,
    "format_bp": _format_bp,
    "format_date": _format_date,
    "format_value": _format_value,
    "format_change": _format_change,
}
_env.filters.update(_FILTERS)
