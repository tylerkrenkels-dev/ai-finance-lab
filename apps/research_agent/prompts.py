"""Static prompt text and tool schemas for the agent loop.

Separated from ``agent.py`` only for size: the system prompt, the three tool
schemas and the two prompt builders are ~150 lines of constant text with no
logic. ``agent.py`` owns the loop that uses them.
"""

import anthropic

from apps.research_agent.discovery import SourceRef

# The three source-reading tools, as raw Anthropic tool schemas.
READ_TOOLS: list[anthropic.types.ToolParam] = [
    {
        "name": "read_macro_note",
        "description": (
            "Read one published daily macro research note by its date. Returns the "
            "note's structured rate, FX, commodity and equity tables, its data "
            "warnings, and its as-of date. Use a date shown in the source list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_date": {"type": "string", "description": "ISO date, e.g. 2026-09-06"}
            },
            "required": ["note_date"],
        },
    },
    {
        "name": "read_equity_snapshot",
        "description": (
            "Read one company's weekly equity snapshot by ticker (e.g. AAPL, "
            "BHP.AX). Returns computed valuation and profitability figures, plus any "
            "data warning explaining a figure that is not shown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "read_comp_table",
        "description": (
            "Read one precedent-transaction comparables table by its table id "
            "(e.g. splunk-cisco-qatalyst). Returns the deal parties, per-transaction "
            "multiples and summary statistics, each traceable to a cited SEC filing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"table_id": {"type": "string"}},
            "required": ["table_id"],
        },
    },
]

TOOL_CHOICE_NONE: anthropic.types.ToolChoiceNoneParam = {"type": "none"}

_SYSTEM_PARAGRAPHS = [
    (
        "You are a research assistant answering one question using only three "
        "internal sources: a daily macro research note series, weekly single-company "
        "equity snapshots, and a set of M&A precedent-transaction comparables "
        "tables. You reach them through the read tools provided. Every figure in "
        "those sources has already been computed and validated by other software."
    ),
    (
        "First gather what you need. The available sources are listed in the user "
        "message. Call a read tool only for a source you expect to cite. When you "
        "have read enough to answer, stop calling tools."
    ),
    (
        "You must never calculate, estimate, infer, interpolate, round differently, "
        "average, difference, or otherwise produce a number that is not already "
        "present verbatim in a source you have read. If a comparison would require "
        "arithmetic you have not been given the result of, describe the relationship "
        'in words only ("richer", "wider", "higher") with no new number.'
    ),
    (
        "Then write the answer as a single JSON object and nothing else -- no "
        'markdown fences, no text around it -- with exactly two fields: "question" '
        '(a string) and "claims" (an array). Each claim is an object with exactly '
        '"text" (a string) and "citation" (a string).'
    ),
    (
        "Each claim states exactly one fact and cites exactly one source, by the "
        "doc_id of a page you read. Cite the source the claim is about -- the Apple "
        "page for a claim about Apple -- not the page a number happened to appear "
        "on. A sentence that draws on two sources must be split into two claims. "
        'Set "citation" to "none" only for connective prose that contains no number.'
    ),
    (
        "Every number in a claim must appear, character for character (same digits, "
        "same unit, same trailing zeros), in that claim's cited source. Do not "
        "restate a percent as a multiple or vice versa. Never state a change, "
        "trend, streak, or cross-date movement unless the cited source itself "
        "publishes that exact figure as a labelled change."
    ),
    (
        "If a figure is missing from a source, you may say so only by reproducing "
        "that source's own data-warning text for it -- the specific published "
        'reason, not a vague "not available". If a source is marked stale or '
        "carries an older as-of date, say so in any claim that quotes it."
    ),
    (
        "Write in a neutral, professional register for institutional readers. Do "
        "not use markdown formatting inside the JSON string values."
    ),
]
SYSTEM_PROMPT = "\n\n".join(_SYSTEM_PARAGRAPHS)

GENERATION_INSTRUCTION = (
    "You have finished reading. Now output the research answer as the single JSON "
    "object described in the system instructions, and nothing else."
)

_MANIFEST_TOOLS = {
    "macro_note": ("read_macro_note", "note_date"),
    "equity_snapshot": ("read_equity_snapshot", "ticker"),
    "comps": ("read_comp_table", "table_id"),
}


def render_manifest(refs: list[SourceRef]) -> str:
    """Group the available sources by system into a compact, model-readable list."""
    lines: list[str] = []
    for system, (tool, arg) in _MANIFEST_TOOLS.items():
        group = [ref for ref in refs if ref.system == system]
        if not group:
            continue
        lines.append(f"{system} -- call {tool}({arg}=...):")
        lines.extend(f"  {ref.key}  {ref.label}  (as of {ref.as_of.isoformat()})" for ref in group)
    return "\n".join(lines)


def retrieval_prompt(question: str, manifest: str) -> str:
    return (
        f"Question: {question}\n\n"
        f"Available sources:\n{manifest}\n\n"
        "Read the sources you need to answer, then stop calling tools."
    )
