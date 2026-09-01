import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic

from apps.equity_snapshot.narrative import (
    AnthropicSettings,
    NarrativeGenerator,
    NarrativeParseError,
    TickerNarrative,
)
from apps.equity_snapshot.payload import EquitySnapshot, build_equity_snapshot
from tests.apps.equity_snapshot.test_calculations import _BHP


def _settings() -> AnthropicSettings:
    return AnthropicSettings(anthropic_api_key="test-key")


def _snapshot() -> EquitySnapshot:
    # Real BHP.AX data (same fixture test_calculations.py/test_payload.py already
    # hand-verified), chosen deliberately because it carries a real
    # currency-mismatch data_warning -- the one novel risk this system's prompt
    # has to guard against that macro_note's never did.
    return build_equity_snapshot(_BHP)


def _narrative() -> TickerNarrative:
    return TickerNarrative(
        headline="BHP trades at a premium valuation with strong profitability",
        summary=(
            "BHP Group Limited trades at a trailing P/E of 24.76x and a forward P/E of 18.62x."
        ),
    )


def _text_response(text: str) -> SimpleNamespace:
    """A stand-in for anthropic.types.Message, shaped the way _extract_text reads it."""
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _narrative_response(narrative: TickerNarrative) -> SimpleNamespace:
    return _text_response(narrative.model_dump_json())


def test_generate_returns_parsed_narrative() -> None:
    expected = _narrative()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(expected)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    narrative = generator.generate(_snapshot())

    assert narrative == expected
    mock_client.messages.create.assert_called_once()


def test_generate_makes_exactly_one_api_call() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_snapshot())

    assert mock_client.messages.create.call_count == 1


def test_generate_calls_with_expected_model_and_temperature() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_snapshot())

    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["temperature"] == 0
    assert "output_format" not in kwargs


def test_generate_system_prompt_forbids_computation() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_snapshot())

    _, kwargs = mock_client.messages.create.call_args
    system = kwargs["system"]
    assert "never calculate, estimate, infer" in system
    assert "reproduced exactly as given" in system


def test_generate_system_prompt_specifies_json_format_with_no_bullets() -> None:
    # Deliberately confirms "bullets" is NOT requested -- TickerNarrative has no
    # bullets field, unlike NoteNarrative; this is a structural difference from
    # macro_note, not an oversight, and worth asserting explicitly.
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_snapshot())

    _, kwargs = mock_client.messages.create.call_args
    system = kwargs["system"]
    assert "no markdown code fences" in system
    assert '"headline"' in system
    assert '"summary"' in system
    assert '"bullets"' not in system


def test_generate_system_prompt_guards_against_currency_bridging() -> None:
    # The novel risk this system's prompt has to cover, absent from macro_note:
    # a data_warning that explains WHY a figure is missing (e.g. a currency
    # mismatch) hands the model enough context to attempt an estimate -- the
    # prompt must explicitly forbid using that explanation as license to compute.
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_snapshot())

    _, kwargs = mock_client.messages.create.call_args
    system = kwargs["system"]
    assert "not an invitation to compute, convert, or estimate" in system
    assert "data_warnings" in system


def test_generate_system_prompt_tells_model_to_reproduce_market_cap_display_verbatim() -> None:
    # market_cap is a raw integer; "~A$341 billion" is a scale-and-round the model
    # must not perform. payload.py carries a canonical market_cap_display string
    # and the prompt must direct the model to reproduce it, not transform the int.
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_snapshot())

    _, kwargs = mock_client.messages.create.call_args
    system = kwargs["system"]
    assert "market_cap_display" in system
    assert "reproduce the market_cap_display string exactly as given" in system


def test_generate_prompt_includes_snapshot_as_json() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)
    snapshot = _snapshot()

    generator.generate(snapshot)

    _, kwargs = mock_client.messages.create.call_args
    user_content = kwargs["messages"][0]["content"]
    assert snapshot.model_dump_json(indent=2) in user_content
    assert snapshot.ticker in user_content


def test_generate_raises_narrative_parse_error_when_response_has_no_text_block() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(content=[])
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    try:
        generator.generate(_snapshot())
    except NarrativeParseError:
        pass
    else:
        raise AssertionError("expected NarrativeParseError when response has no text block")


def test_generate_raises_narrative_parse_error_on_missing_required_field() -> None:
    """Reproduces the real production failure class macro_note's #44 found: a valid
    JSON response that doesn't satisfy the response model's shape. TickerNarrative
    has no length-capped field to violate (unlike NoteNarrative.bullets), so this
    uses a missing required field instead -- same failure class, adapted shape."""
    fabricated_text = json.dumps({"headline": "BHP Surges"})  # summary missing
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response(fabricated_text)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    try:
        generator.generate(_snapshot())
    except NarrativeParseError as exc:
        assert exc.raw_text == fabricated_text
    else:
        raise AssertionError("expected NarrativeParseError for a missing required field")


def test_generate_raises_narrative_parse_error_on_malformed_json() -> None:
    fabricated_text = '{"headline": "BHP Surges", "summary": "Broken json'
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response(fabricated_text)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    try:
        generator.generate(_snapshot())
    except NarrativeParseError as exc:
        assert exc.raw_text == fabricated_text
    else:
        raise AssertionError("expected NarrativeParseError for malformed JSON")


def test_generate_recovers_from_a_markdown_code_fence() -> None:
    """The prompt asks for no fences, but a fenced response is a common enough model
    habit to recover from rather than fail the run over -- see _strip_code_fence."""
    expected = _narrative()
    fenced_text = f"```json\n{expected.model_dump_json()}\n```"
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response(fenced_text)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    narrative = generator.generate(_snapshot())

    assert narrative == expected


def test_generate_raises_narrative_parse_error_with_original_text_when_fence_recovery_fails() -> (
    None
):
    """A fenced-but-still-invalid response must still fail loudly, with the raw_text
    on the exception equal to the original (fenced) text, not the stripped attempt."""
    fabricated_text = '```json\n{"headline": "BHP Surges", "summary": "Broken\n```'
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response(fabricated_text)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    try:
        generator.generate(_snapshot())
    except NarrativeParseError as exc:
        assert exc.raw_text == fabricated_text
    else:
        raise AssertionError("expected NarrativeParseError for a fenced but malformed response")


def test_narrative_generator_constructs_client_from_settings_when_omitted() -> None:
    # Constructing anthropic.Anthropic() only stores the key; it makes no network call.
    generator = NarrativeGenerator(settings=_settings())

    assert isinstance(generator._client, anthropic.Anthropic)
