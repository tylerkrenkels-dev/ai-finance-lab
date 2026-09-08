"""Tests for the Research Agent answer renderer.

``render_answer`` joins the surviving claims into one paragraph with ``[n]``
markers and appends a references block; ``render_refusal`` is the text shown when
too little could be verified. Both are pure. SourcePages are built through the
real ``read_*`` tools against the committed fixtures, never hand-rolled.
"""

from pathlib import Path

from apps.research_agent.models import NO_CITATION, Claim, ResearchAnswer
from apps.research_agent.render import render_answer, render_refusal
from apps.research_agent.sources import read_equity_snapshot

_FIXTURES = Path(__file__).parent / "fixtures"


def _retrieved(*pages):
    return {page.doc_id: page for page in pages}


def _aapl():
    return read_equity_snapshot("AAPL", docs_dir=_FIXTURES)


def _msft():
    return read_equity_snapshot("MSFT", docs_dir=_FIXTURES)


def test_single_claim_gets_one_marker_and_one_reference() -> None:
    answer = ResearchAnswer(
        question="q",
        claims=[Claim(text="Apple trades at 37.33x.", citation="equity_snapshot/AAPL")],
    )
    out = render_answer(answer, _retrieved(_aapl()))
    assert "Apple trades at 37.33x. [1]" in out
    assert "[1] equity_snapshot/AAPL — " in out
    assert out.rstrip().endswith("aapl.md")


def test_distinct_sources_numbered_in_first_appearance_order() -> None:
    answer = ResearchAnswer(
        question="q",
        claims=[
            Claim(text="MSFT ROE is 34.04%.", citation="equity_snapshot/MSFT"),
            Claim(text="AAPL ROE is 148.75%.", citation="equity_snapshot/AAPL"),
        ],
    )
    out = render_answer(answer, _retrieved(_aapl(), _msft()))
    assert "MSFT ROE is 34.04%. [1]" in out
    assert "AAPL ROE is 148.75%. [2]" in out
    assert "[1] equity_snapshot/MSFT" in out
    assert "[2] equity_snapshot/AAPL" in out


def test_claims_sharing_a_source_share_a_marker() -> None:
    answer = ResearchAnswer(
        question="q",
        claims=[
            Claim(text="AAPL trades at 37.33x.", citation="equity_snapshot/AAPL"),
            Claim(text="AAPL forward P/E is 34.09x.", citation="equity_snapshot/AAPL"),
        ],
    )
    out = render_answer(answer, _retrieved(_aapl()))
    assert "37.33x. [1]" in out and "34.09x. [1]" in out
    assert out.count("[1] equity_snapshot/AAPL") == 1
    assert "[2]" not in out


def test_none_citation_claim_has_no_marker() -> None:
    answer = ResearchAnswer(
        question="q",
        claims=[
            Claim(text="Both are technology leaders.", citation=NO_CITATION),
            Claim(text="AAPL trades at 37.33x.", citation="equity_snapshot/AAPL"),
        ],
    )
    out = render_answer(answer, _retrieved(_aapl()))
    assert "Both are technology leaders. " in out
    assert "Both are technology leaders. [" not in out
    assert "37.33x. [1]" in out


def test_refusal_names_sorted_sources_and_reason() -> None:
    out = render_refusal(
        "What is X?",
        ["equity_snapshot/MSFT", "equity_snapshot/AAPL"],
        "Could not verify.",
    )
    assert "What is X?" in out
    assert "Could not verify." in out
    assert "equity_snapshot/AAPL, equity_snapshot/MSFT" in out


def test_refusal_with_no_sources_says_none() -> None:
    out = render_refusal("q", [], "No source found.")
    assert "none" in out
