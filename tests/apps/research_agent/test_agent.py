"""Tests for the Research Agent loop.

The Anthropic API is the only thing scripted -- ``FakeAnthropic`` replays a fixed
queue of messages. The three source-reading tools, the citation guard, the
renderer and the fixture pages are all real, per CLAUDE.md section 6 ("recorded
fixtures or cassettes, never live calls"). The one genuinely-live check is
``test_live_api_smoke``, marked ``network`` and excluded from CI.

Orchestration cases, mapped to the design's hand-traced scenarios:
  clean run                         -> guard passes first try, renders
  ROE misattribution (case 1 / S3)  -> fail_fast triage trips -> one retry -> fixed
  unfixable claim                   -> withheld, not shown, partial answer
  majority unverified               -> full refusal naming sources consulted
  no sources read                   -> refusal
  unparseable answer                -> refusal
  step ceiling                      -> retrieval force-stops, generation still runs
The other hand-traced cases (2, 4-6, 7-9) have guard-level coverage in
test_guards.py; this file drives cases 1 and 3-shaped defects through run().
"""

import json
from pathlib import Path

import pytest

from apps.research_agent.agent import MAX_RETRIEVAL_STEPS, run
from apps.research_agent.models import NO_CITATION

_FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------- fake Anthropic


class _FakeBlock:
    def __init__(self, **kw: object) -> None:
        self.__dict__.update(kw)


class _FakeMessage:
    def __init__(self, stop_reason: str, content: list[_FakeBlock]) -> None:
        self.stop_reason = stop_reason
        self.content = content


def _tool_use(*calls: tuple[str, dict[str, str]]) -> _FakeMessage:
    return _FakeMessage(
        "tool_use",
        [
            _FakeBlock(type="tool_use", id=f"tu_{i}", name=name, input=inp)
            for i, (name, inp) in enumerate(calls)
        ],
    )


def _final(text: str) -> _FakeMessage:
    return _FakeMessage("end_turn", [_FakeBlock(type="text", text=text)])


class FakeAnthropic:
    """Replays a fixed queue of messages; records every ``create`` kwargs dict."""

    def __init__(self, *responses: _FakeMessage) -> None:
        self._queue = list(responses)
        self.create_calls: list[dict[str, object]] = []
        self.messages = self

    def create(self, **kwargs: object) -> _FakeMessage:
        self.create_calls.append(kwargs)
        if not self._queue:
            raise AssertionError("FakeAnthropic ran out of scripted responses")
        return self._queue.pop(0)


def _answer_json(claims: list[tuple[str, str]], question: str = "q") -> str:
    return json.dumps(
        {
            "question": question,
            "claims": [{"text": text, "citation": cite} for text, cite in claims],
        }
    )


_READ_AAPL = ("read_equity_snapshot", {"ticker": "AAPL"})
_READ_MSFT = ("read_equity_snapshot", {"ticker": "MSFT"})


# ------------------------------------------------------------------- the cases


def test_clean_run_answers_and_exits_zero() -> None:
    client = FakeAnthropic(
        _tool_use(_READ_AAPL, _READ_MSFT),
        _final(
            _answer_json(
                [
                    (
                        "Apple Inc. trades at a trailing price-to-earnings ratio of 37.33x.",
                        "equity_snapshot/AAPL",
                    ),
                    (
                        "Microsoft Corporation posts a return on equity of 34.04%.",
                        "equity_snapshot/MSFT",
                    ),
                    (
                        "Apple's return on equity of 148.75% reflects efficient "
                        "capital deployment.",
                        "equity_snapshot/AAPL",
                    ),
                ]
            )
        ),
    )
    result = run("How do Apple and Microsoft compare?", docs_dir=_FIXTURES, client=client)

    assert result.outcome == "answered"
    assert result.exit_code == 0
    assert not result.retried
    assert result.withheld == []
    assert len(result.attempts) == 1
    assert result.attempts[-1].violations == []
    assert "[1]" in result.rendered and "References" in result.rendered
    assert [call.doc_id for call in result.tool_calls] == [
        "equity_snapshot/AAPL",
        "equity_snapshot/MSFT",
    ]


def test_misattribution_triggers_one_retry_then_answers() -> None:
    bad = _answer_json(
        [("Apple's return on equity of 34.04% is remarkable.", "equity_snapshot/AAPL")]
    )
    good = _answer_json(
        [("Apple's return on equity of 148.75% is remarkable.", "equity_snapshot/AAPL")]
    )
    client = FakeAnthropic(
        _tool_use(_READ_AAPL, _READ_MSFT),
        _final(bad),
        _final(good),
    )
    result = run("What is Apple's ROE?", docs_dir=_FIXTURES, client=client)

    assert result.retried
    assert any(
        v.figure == "34.04%" and v.kind == "figure_not_in_citation"
        for v in result.attempts[0].violations
    )
    assert result.outcome == "answered"
    assert result.attempts[-1].violations == []
    assert "148.75%" in result.rendered
    assert "34.04%" not in result.rendered


def test_unfixable_claim_is_withheld_not_shown() -> None:
    claims = [
        ("Apple Inc. trades at a trailing P/E of 37.33x.", "equity_snapshot/AAPL"),
        ("Microsoft Corporation posts a return on equity of 34.04%.", "equity_snapshot/MSFT"),
        ("Apple's return on equity of 34.04% is remarkable.", "equity_snapshot/AAPL"),
    ]
    client = FakeAnthropic(
        _tool_use(_READ_AAPL, _READ_MSFT),
        _final(_answer_json(claims)),
        _final(_answer_json(claims)),  # retry does not fix it
    )
    result = run("Compare AAPL and MSFT", docs_dir=_FIXTURES, client=client)

    assert result.outcome == "partial"
    assert result.withheld == [2]
    assert result.exit_code == 0
    assert "34.04% is remarkable" not in result.rendered
    assert "37.33x" in result.rendered
    assert "could not be verified" in result.rendered


def test_majority_unverified_is_a_full_refusal() -> None:
    claims = [
        ("Apple's return on equity of 34.04% is remarkable.", "equity_snapshot/AAPL"),
        ("Microsoft Corporation trades at a trailing P/E of 37.33x.", "equity_snapshot/MSFT"),
        ("Apple Inc. reports a forward P/E of 34.09x.", "equity_snapshot/AAPL"),
    ]
    client = FakeAnthropic(
        _tool_use(_READ_AAPL, _READ_MSFT),
        _final(_answer_json(claims)),
        _final(_answer_json(claims)),
    )
    result = run("Compare AAPL and MSFT", docs_dir=_FIXTURES, client=client)

    assert result.outcome == "refused"
    assert result.exit_code == 1
    # The failing draft is kept on the result for the transcript, never rendered.
    assert "is remarkable" not in result.rendered
    assert "34.09x" not in result.rendered
    assert "Sources consulted: equity_snapshot/AAPL, equity_snapshot/MSFT" in result.rendered


def test_no_sources_read_is_a_refusal() -> None:
    client = FakeAnthropic(_final("I don't have enough to answer that."))
    result = run("What is the meaning of life?", docs_dir=_FIXTURES, client=client)

    assert result.outcome == "refused"
    assert result.exit_code == 1
    assert result.attempts == []
    assert "No relevant source" in result.rendered
    assert len(client.create_calls) == 1


def test_unparseable_answer_is_a_refusal() -> None:
    client = FakeAnthropic(
        _tool_use(_READ_AAPL),
        _final("Sorry, I can't produce that."),
        _final("Still cannot."),  # explicit generation retry also fails to parse
    )
    result = run("What is Apple's ROE?", docs_dir=_FIXTURES, client=client)

    assert result.outcome == "refused"
    assert result.exit_code == 1


def test_retrieval_stops_at_the_step_ceiling(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeAnthropic(
        *[_tool_use(_READ_AAPL) for _ in range(MAX_RETRIEVAL_STEPS)],
        _final(
            _answer_json([("Apple's return on equity of 148.75% is high.", "equity_snapshot/AAPL")])
        ),
    )
    with caplog.at_level("WARNING"):
        result = run("q", docs_dir=_FIXTURES, client=client)

    assert len(result.tool_calls) == MAX_RETRIEVAL_STEPS
    assert "ceiling" in caplog.text
    assert result.outcome == "answered"


def test_tool_calls_are_recorded_in_order() -> None:
    client = FakeAnthropic(
        _tool_use(_READ_MSFT),
        _tool_use(_READ_AAPL),
        _final(
            _answer_json(
                [("Apple Inc. trades at a trailing P/E of 37.33x.", "equity_snapshot/AAPL")]
            )
        ),
    )
    result = run("q", docs_dir=_FIXTURES, client=client)

    assert [(c.name, c.args) for c in result.tool_calls] == [
        ("read_equity_snapshot", {"ticker": "MSFT"}),
        ("read_equity_snapshot", {"ticker": "AAPL"}),
    ]


def test_worked_example_end_to_end_with_real_source_tools() -> None:
    question = "How do Apple and Microsoft compare on profitability and valuation?"
    client = FakeAnthropic(
        _tool_use(_READ_AAPL, _READ_MSFT),
        _final(
            _answer_json(
                [
                    (
                        "Apple Inc. is valued at USD 4.75 trillion with a trailing P/E of 37.33x.",
                        "equity_snapshot/AAPL",
                    ),
                    (
                        "Apple Inc. reports a forward P/E of 34.09x and an EV/EBITDA of 28.38x.",
                        "equity_snapshot/AAPL",
                    ),
                    (
                        "Microsoft Corporation trades at a trailing P/E of 27.90x.",
                        "equity_snapshot/MSFT",
                    ),
                    (
                        "Microsoft Corporation posts a gross margin of 67.94% and an "
                        "operating margin of 45.11%.",
                        "equity_snapshot/MSFT",
                    ),
                    ("Both are premium technology-sector names.", NO_CITATION),
                ],
                question=question,
            )
        ),
    )
    result = run(question, docs_dir=_FIXTURES, client=client)

    assert result.outcome == "answered"
    assert result.retried is False
    assert "trailing P/E of 37.33x. [1]" in result.rendered
    assert "trailing P/E of 27.90x. [2]" in result.rendered
    assert "Both are premium technology-sector names." in result.rendered
    assert "[1] equity_snapshot/AAPL" in result.rendered
    assert "[2] equity_snapshot/MSFT" in result.rendered


@pytest.mark.network
def test_live_api_smoke() -> None:
    """A genuine end-to-end run against the live API and the committed docs/."""
    result = run(
        "How do Apple and Microsoft compare on profitability and valuation?",
        docs_dir=Path("docs"),
    )
    assert result.outcome in {"answered", "partial"}
    assert result.rendered.strip()
