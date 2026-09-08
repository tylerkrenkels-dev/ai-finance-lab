"""The Research Agent loop: question in, source-cited answer out.

Three phases in ``run()``:

1. **Retrieval** -- a bounded tool-calling loop. ``list_available_sources`` is
   rendered into the first user message (discovery is deterministic, not a tool);
   the model then calls the three ``read_*`` tools for the pages it will cite.
   The loop ends when the model stops calling tools, hard-capped at
   ``MAX_RETRIEVAL_STEPS`` turns. No sources read -> refusal.
2. **Generation** -- a ``ResearchAnswer``. The system prompt asks for the JSON in
   the same turn the model stops reading, so the terminal retrieval text usually
   is the answer; only if it does not validate is one extra call made. Plain
   ``messages.create`` + manual validation, not ``messages.parse`` (#19/#44).
3. **Verification** -- ``check_citations`` ``fail_fast`` triage; on a hit,
   ``collect_all`` feeds every violation back for exactly one retry, then
   ``collect_all`` again. Claims that still fail are withheld by index; if none
   survive or more than half were withheld, the result refuses and names the
   sources consulted. A failing draft is never rendered.

The numeric invariant holds: every number in a claim must already appear,
character for character, in that claim's one cited source; the guard enforces it.

``prompts`` holds the static text and tool schemas; ``__main__`` is the CLI.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

import anthropic
import pydantic
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.research_agent.discovery import list_available_sources
from apps.research_agent.guards import (
    CitationGuardError,
    CitationViolation,
    check_citations,
    enforce_citations,
    render_retry_feedback,
)
from apps.research_agent.models import ResearchAnswer, SourcePage
from apps.research_agent.prompts import (
    GENERATION_INSTRUCTION,
    READ_TOOLS,
    SYSTEM_PROMPT,
    TOOL_CHOICE_NONE,
    render_manifest,
    retrieval_prompt,
)
from apps.research_agent.render import render_answer, render_refusal
from apps.research_agent.sources import (
    DEFAULT_DOCS_DIR,
    read_comp_table,
    read_equity_snapshot,
    read_macro_note,
)

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 2048
MAX_RETRIEVAL_STEPS = 6
"""Hard ceiling on retrieval model-turns. Insurance only -- normal operation
stops earlier, when the model stops calling tools. Provisional pending live use,
like the sibling apps' token bounds."""

Outcome = Literal["answered", "partial", "refused"]


class AnthropicSettings(BaseSettings):
    """Anthropic API credentials, read from .env. Never hardcoded.

    A third verbatim copy of the class in ``apps.macro_note.narrative`` and
    ``apps.equity_snapshot.narrative``. Extraction to ``core/`` is deferred to its
    own issue: this app's LLM interaction (a tool-calling loop) differs enough
    from the siblings' one-shot calls that only this 3-line class is a true
    rule-of-three hit, and CLAUDE.md forbids abstracting mid-task.
    """

    anthropic_api_key: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@dataclass(frozen=True)
class ToolCall:
    """One read-tool invocation the model made, in loop order."""

    name: str
    args: dict[str, str]
    doc_id: str | None
    ok: bool


@dataclass(frozen=True)
class Attempt:
    """One draft and its guard result: the first answer, then the retry if any."""

    answer: ResearchAnswer | None
    violations: list[CitationViolation]


@dataclass(frozen=True)
class AgentResult:
    """Everything one ``run()`` produced -- the output plus the audit trail."""

    outcome: Outcome
    rendered: str
    tool_calls: list[ToolCall]
    retrieved: list[str]
    attempts: list[Attempt]
    withheld: list[int]

    @property
    def retried(self) -> bool:
        return len(self.attempts) > 1

    @property
    def exit_code(self) -> int:
        """0 for a full or partial answer, 1 for a refusal."""
        return 0 if self.outcome in ("answered", "partial") else 1


class AgentAnswerError(RuntimeError):
    """The model's response did not validate into a ``ResearchAnswer``.

    Carries the raw text, which a bare ``pydantic.ValidationError`` discards.
    """

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


def run(
    question: str,
    docs_dir: Path = DEFAULT_DOCS_DIR,
    *,
    client: anthropic.Anthropic | None = None,
    model: str = MODEL,
) -> AgentResult:
    """Answer `question` from the three source systems, with a one-shot guard retry.

    `client` defaults to a real one built from .env. The returned ``AgentResult``
    carries the ``rendered`` text to show the user, the tool calls, every draft
    with its guard result, and an ``exit_code`` (0 for an answer, 1 for refusal).
    """
    client = client or _default_client()
    manifest = render_manifest(list_available_sources(docs_dir))
    retrieved, tool_calls, messages, terminal_text = _retrieve(
        client, question, manifest, docs_dir, model
    )
    if not retrieved:
        return _refuse(
            question, retrieved, tool_calls, [], "No relevant source could be identified."
        )

    try:
        first = _answer(client, messages, model, terminal_text)
    except AgentAnswerError:
        logger.exception("first answer did not parse")
        return _refuse(
            question,
            retrieved,
            tool_calls,
            [Attempt(None, [])],
            "The answer could not be produced in a verifiable form.",
        )

    if not check_citations(first, retrieved, mode="fail_fast"):
        return _assemble(question, retrieved, tool_calls, [Attempt(first, [])])

    attempts = [Attempt(first, check_citations(first, retrieved, mode="collect_all"))]
    messages.append(
        {"role": "user", "content": render_retry_feedback(attempts[0].violations, retrieved)}
    )
    try:
        retry = _generate(client, messages, model)
    except AgentAnswerError:
        logger.exception("retry answer did not parse")
        return _refuse(
            question,
            retrieved,
            tool_calls,
            [*attempts, Attempt(None, [])],
            "The answer could not be verified against its sources.",
        )

    final = check_citations(retry, retrieved, mode="collect_all")
    return _assemble(question, retrieved, tool_calls, [*attempts, Attempt(retry, final)])


def _retrieve(
    client: anthropic.Anthropic,
    question: str,
    manifest: str,
    docs_dir: Path,
    model: str,
) -> tuple[dict[str, SourcePage], list[ToolCall], list[anthropic.types.MessageParam], str | None]:
    """Run the bounded tool-calling loop.

    Returns the retrieved pages, the calls made, the message history, and the
    text of the terminating turn (``None`` if the step ceiling was hit) -- which
    the caller tries to parse as the answer before spending another call.
    """
    messages: list[anthropic.types.MessageParam] = [
        {"role": "user", "content": retrieval_prompt(question, manifest)}
    ]
    retrieved: dict[str, SourcePage] = {}
    calls: list[ToolCall] = []

    for _ in range(MAX_RETRIEVAL_STEPS):
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            temperature=0,
            system=SYSTEM_PROMPT,
            tools=READ_TOOLS,
            messages=messages,
        )
        messages.append(_assistant_turn(response.content))
        results = _run_tool_batch(response, docs_dir, retrieved, calls)
        if not results:
            return retrieved, calls, messages, _maybe_text(response)
        messages.append(_tool_results_turn(results))

    logger.warning(
        "retrieval hit the %d-step ceiling; generating with %d source(s)",
        MAX_RETRIEVAL_STEPS,
        len(retrieved),
    )
    return retrieved, calls, messages, None


def _run_tool_batch(
    response: anthropic.types.Message,
    docs_dir: Path,
    retrieved: dict[str, SourcePage],
    calls: list[ToolCall],
) -> list[dict[str, Any]]:
    """Execute every ``tool_use`` block in `response`; mutate `retrieved`/`calls`.

    Returns the ``tool_result`` blocks to send back (empty when the model made no
    tool call -- its signal that retrieval is done).
    """
    results: list[dict[str, Any]] = []
    for block in response.content:
        if block.type != "tool_use":
            continue
        args = cast("dict[str, str]", block.input)
        page, payload, is_error = _execute_read(block.name, args, docs_dir)
        calls.append(
            ToolCall(
                name=block.name,
                args=dict(args),
                doc_id=page.doc_id if page is not None else None,
                ok=page is not None,
            )
        )
        if page is not None:
            retrieved[page.doc_id] = page
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": payload,
                "is_error": is_error,
            }
        )
    return results


def _execute_read(
    name: str, args: dict[str, str], docs_dir: Path
) -> tuple[SourcePage | None, str, bool]:
    """Dispatch one read tool. Returns ``(page, payload_or_error_text, is_error)``.

    ``SourcePageIntegrityError`` is deliberately not caught -- an equity page with
    an unexplained missing figure must fail the whole run loudly, per sources.py.
    """
    try:
        if name == "read_macro_note":
            page = read_macro_note(date.fromisoformat(args["note_date"]), docs_dir=docs_dir)
        elif name == "read_equity_snapshot":
            page = read_equity_snapshot(args["ticker"], docs_dir=docs_dir)
        elif name == "read_comp_table":
            page = read_comp_table(args["table_id"], docs_dir=docs_dir)
        else:
            return None, f"Unknown tool {name!r}.", True
    except (KeyError, ValueError, TypeError) as exc:
        return None, f"Could not read source: {exc}", True

    if page is None:
        return None, "No such source; choose one from the list provided.", True
    return page, json.dumps(_page_view(page), indent=2), False


def _page_view(page: SourcePage) -> dict[str, Any]:
    """The model-facing view of a SourcePage: structured cells and warnings only.

    ``raw_markdown`` is withheld deliberately -- the model synthesises from
    validated cells, not another system's model-authored prose. The full page
    stays in the retrieved dict for the guard and the reference list.
    """
    return {
        "doc_id": page.doc_id,
        "system": page.system,
        "as_of": page.as_of.isoformat(),
        "stale": page.stale,
        "subject_terms": list(page.subject_terms),
        "data_warnings": list(page.data_warnings),
        "sections": [
            {"heading": section.heading, "rows": section.rows} for section in page.sections
        ],
    }


def _answer(
    client: anthropic.Anthropic,
    messages: list[anthropic.types.MessageParam],
    model: str,
    terminal_text: str | None,
) -> ResearchAnswer:
    """The ResearchAnswer, from the terminal retrieval turn if it already is one.

    Only if ``terminal_text`` does not validate is one extra call made with an
    explicit instruction.
    """
    if terminal_text is not None:
        try:
            return _parse_answer(terminal_text)
        except AgentAnswerError:
            logger.info("terminal retrieval turn was not the answer JSON; asking explicitly")
    messages.append({"role": "user", "content": GENERATION_INSTRUCTION})
    return _generate(client, messages, model)


def _generate(
    client: anthropic.Anthropic, messages: list[anthropic.types.MessageParam], model: str
) -> ResearchAnswer:
    """One constrained call; validate the response text into a ``ResearchAnswer``."""
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system=SYSTEM_PROMPT,
        tools=READ_TOOLS,
        tool_choice=TOOL_CHOICE_NONE,
        messages=messages,
    )
    messages.append(_assistant_turn(response.content))
    return _parse_answer(_extract_text(response))


def _parse_answer(text: str) -> ResearchAnswer:
    """Validate `text` (optionally code-fenced) into a ``ResearchAnswer``."""
    for candidate in _json_candidates(text):
        try:
            return ResearchAnswer.model_validate_json(candidate)
        except pydantic.ValidationError:
            continue
    raise AgentAnswerError(f"response did not validate into ResearchAnswer: {text!r}", text)


def _assemble(
    question: str,
    retrieved: Mapping[str, SourcePage],
    tool_calls: list[ToolCall],
    attempts: list[Attempt],
) -> AgentResult:
    """Withhold still-failing claims from the last attempt; refuse if too few survive."""
    answer = attempts[-1].answer
    violations = attempts[-1].violations
    assert answer is not None  # _assemble is only called with a parsed final answer

    withheld = sorted({v.claim_index for v in violations})
    kept = [claim for i, claim in enumerate(answer.claims) if i not in withheld]
    if not kept or len(withheld) * 2 > len(answer.claims):
        return _refuse(
            question,
            retrieved,
            tool_calls,
            attempts,
            "Too few claims could be verified against their sources to answer.",
        )

    surviving = ResearchAnswer(question=question, claims=kept)
    try:
        enforce_citations(surviving, retrieved)  # final gate; should never fire
    except CitationGuardError:
        logger.exception("surviving-claim set failed the final citation gate")
        return _refuse(
            question,
            retrieved,
            tool_calls,
            attempts,
            "The verified answer failed a final integrity check.",
        )

    rendered = render_answer(surviving, retrieved)
    if withheld:
        rendered += (
            f"\n\n{len(withheld)} claim(s) could not be verified against their "
            "sources and were withheld."
        )
    return AgentResult(
        outcome="partial" if withheld else "answered",
        rendered=rendered,
        tool_calls=tool_calls,
        retrieved=sorted(retrieved),
        attempts=attempts,
        withheld=withheld,
    )


def _refuse(
    question: str,
    retrieved: Mapping[str, SourcePage],
    tool_calls: list[ToolCall],
    attempts: list[Attempt],
    reason: str,
) -> AgentResult:
    return AgentResult(
        outcome="refused",
        rendered=render_refusal(question, retrieved, reason),
        tool_calls=tool_calls,
        retrieved=sorted(retrieved),
        attempts=attempts,
        withheld=[],
    )


def _assistant_turn(content: object) -> anthropic.types.MessageParam:
    """Wrap a response's ``content`` list as an assistant turn to replay.

    ``response.content`` is response ``ContentBlock`` objects, statically not
    ``Iterable[ContentBlockParam]``; the SDK accepts them as history, so cast.
    """
    return cast("anthropic.types.MessageParam", {"role": "assistant", "content": content})


def _tool_results_turn(results: list[dict[str, Any]]) -> anthropic.types.MessageParam:
    """Wrap a batch of ``tool_result`` blocks as the user turn that answers them."""
    return cast("anthropic.types.MessageParam", {"role": "user", "content": results})


def _extract_text(response: anthropic.types.Message) -> str:
    text = _maybe_text(response)
    if text is None:
        raise AgentAnswerError(
            "Anthropic response contained no text block", raw_text=str(response.content)
        )
    return text


def _maybe_text(response: anthropic.types.Message) -> str | None:
    """The first text block's content, or ``None`` if the turn is all tool use."""
    for block in response.content:
        if block.type == "text":
            return block.text
    return None


def _json_candidates(text: str) -> list[str]:
    candidates = [text]
    unfenced = _strip_code_fence(text)
    if unfenced is not None:
        candidates.append(unfenced)
    return candidates


def _strip_code_fence(text: str) -> str | None:
    """Strip a single wrapping ``` or ```json fence, or return None if unfenced."""
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return None


def _default_client() -> anthropic.Anthropic:
    # pydantic-settings supplies anthropic_api_key from the environment/.env.
    settings = AnthropicSettings()  # type: ignore[call-arg]
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)
