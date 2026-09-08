"""CLI entrypoint: ``python -m apps.research_agent "<question>"``.

One question in, the rendered answer on stdout, exit 0 for an answer (full or
partial) and 1 for a refusal. ``--transcript`` prints the full run trace -- tool
calls in order, each draft with its guard result, the outcome -- to stderr; it is
an operator aid for proving the loop live, not part of the answer.
"""

import argparse
import logging
import sys
from pathlib import Path

from apps.research_agent.agent import AgentResult, Attempt, run
from apps.research_agent.sources import DEFAULT_DOCS_DIR


def format_transcript(result: AgentResult) -> str:
    """A human-readable dump of one run: tool calls, every draft, guard outcomes."""
    lines = ["=== tool calls ==="]
    if result.tool_calls:
        for i, call in enumerate(result.tool_calls, 1):
            lines.append(f"  {i}. {call.name}({call.args}) -> {call.doc_id or '(not found)'}")
    else:
        lines.append("  (none)")

    for i, attempt in enumerate(result.attempts, 1):
        label = "first answer" if i == 1 else "retry answer"
        lines += ["", f"=== {label}: {_guard_line(attempt)} ===", _dump_answer(attempt)]

    lines += ["", f"=== outcome: {result.outcome} (exit {result.exit_code}) ==="]
    if result.withheld:
        lines.append(f"withheld claim indices: {result.withheld}")
    lines += ["", "=== final output ===", result.rendered]
    return "\n".join(lines)


def _guard_line(attempt: Attempt) -> str:
    if attempt.answer is None:
        return "did not parse"
    if not attempt.violations:
        return "guard PASS"
    detail = "; ".join(f"claim {v.claim_index + 1} {v.kind}" for v in attempt.violations)
    return f"guard FAIL -- {detail}"


def _dump_answer(attempt: Attempt) -> str:
    return "  (none)" if attempt.answer is None else attempt.answer.model_dump_json(indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m apps.research_agent",
        description="Ask the research agent one question against the published sources.",
    )
    parser.add_argument("question", help="the research question, quoted")
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=DEFAULT_DOCS_DIR,
        help="published docs root (default: docs)",
    )
    parser.add_argument(
        "--transcript", action="store_true", help="print the full run transcript to stderr"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = run(args.question, docs_dir=args.docs_dir)
    if args.transcript:
        print(format_transcript(result), file=sys.stderr)
    print(result.rendered)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
