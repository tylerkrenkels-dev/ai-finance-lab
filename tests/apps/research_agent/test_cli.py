"""Tests for the CLI wrapper: transcript formatting."""

from apps.research_agent.__main__ import format_transcript
from apps.research_agent.agent import AgentResult, Attempt, ToolCall
from apps.research_agent.guards import CitationViolation
from apps.research_agent.models import Claim, ResearchAnswer


def _result(**overrides: object) -> AgentResult:
    base = {
        "outcome": "answered",
        "rendered": "Apple trades at 37.33x. [1]\n\nReferences\n[1] equity_snapshot/AAPL — x.md",
        "tool_calls": [
            ToolCall("read_equity_snapshot", {"ticker": "AAPL"}, "equity_snapshot/AAPL", True)
        ],
        "retrieved": ["equity_snapshot/AAPL"],
        "attempts": [
            Attempt(
                ResearchAnswer(
                    question="q",
                    claims=[Claim(text="Apple trades at 37.33x.", citation="equity_snapshot/AAPL")],
                ),
                [],
            )
        ],
        "withheld": [],
    }
    base.update(overrides)
    return AgentResult(**base)  # type: ignore[arg-type]


def test_transcript_shows_tool_calls_answer_and_outcome() -> None:
    text = format_transcript(_result())
    assert "1. read_equity_snapshot({'ticker': 'AAPL'}) -> equity_snapshot/AAPL" in text
    assert "first answer: guard PASS" in text
    assert "outcome: answered (exit 0)" in text
    assert "final output" in text


def test_transcript_labels_a_retry_and_its_violations() -> None:
    answer = ResearchAnswer(
        question="q",
        claims=[Claim(text="Apple's ROE is 34.04%.", citation="equity_snapshot/AAPL")],
    )
    violation = CitationViolation(
        claim_index=0,
        claim_text="Apple's ROE is 34.04%.",
        citation="equity_snapshot/AAPL",
        kind="figure_not_in_citation",
        figure="34.04%",
        detail="...",
    )
    result = _result(
        outcome="partial",
        withheld=[0],
        attempts=[Attempt(answer, [violation]), Attempt(answer, [])],
    )
    text = format_transcript(result)
    assert "first answer: guard FAIL -- claim 1 figure_not_in_citation" in text
    assert "retry answer: guard PASS" in text
    assert "withheld claim indices: [0]" in text


def test_transcript_marks_an_unparsed_attempt() -> None:
    text = format_transcript(_result(outcome="refused", attempts=[Attempt(None, [])]))
    assert "first answer: did not parse" in text
    assert "outcome: refused (exit 1)" in text
