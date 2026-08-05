import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic

from apps.macro_note.models import Metric, MetricChange, NoteFacts, NoteNarrative, Section
from apps.macro_note.narrative import AnthropicSettings, NarrativeGenerator, NarrativeParseError

NOTE_DATE = date(2026, 7, 31)

_NO_CHANGE = MetricChange(pct_change=None, bp_change=None, reference_as_of=None)


def _settings() -> AnthropicSettings:
    return AnthropicSettings(anthropic_api_key="test-key")


def _facts() -> NoteFacts:
    metric = Metric(
        series_id="us_10y",
        label="US 10-Year Treasury Yield",
        value=4.25,
        unit="%",
        as_of=NOTE_DATE,
        change_1d=_NO_CHANGE,
        change_1w=_NO_CHANGE,
        change_1m=_NO_CHANGE,
    )
    return NoteFacts(
        note_date=NOTE_DATE,
        sections=[Section(title="Rates", metrics=[metric])],
    )


def _narrative() -> NoteNarrative:
    return NoteNarrative(
        headline="Yields hold steady",
        summary="The US 10-Year Treasury Yield stood at 4.25% as of 2026-07-31.",
        bullets=["US 10-Year Treasury Yield: 4.25%"],
    )


def _text_response(text: str) -> SimpleNamespace:
    """A stand-in for anthropic.types.Message, shaped the way _extract_text reads it."""
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _narrative_response(narrative: NoteNarrative) -> SimpleNamespace:
    return _text_response(narrative.model_dump_json())


def test_generate_returns_parsed_narrative() -> None:
    expected = _narrative()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(expected)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    narrative = generator.generate(_facts())

    assert narrative == expected
    mock_client.messages.create.assert_called_once()


def test_generate_makes_exactly_one_api_call() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_facts())

    assert mock_client.messages.create.call_count == 1


def test_generate_calls_with_expected_model_and_temperature() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_facts())

    _, kwargs = mock_client.messages.create.call_args
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["temperature"] == 0
    assert "output_format" not in kwargs


def test_generate_system_prompt_forbids_computation() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_facts())

    _, kwargs = mock_client.messages.create.call_args
    system = kwargs["system"]
    assert "never calculate, estimate, infer" in system
    assert "reproduced exactly as given" in system


def test_generate_system_prompt_specifies_json_format() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_facts())

    _, kwargs = mock_client.messages.create.call_args
    system = kwargs["system"]
    assert "no markdown code fences" in system
    assert '"headline"' in system
    assert '"summary"' in system
    assert '"bullets"' in system


def test_generate_prompt_includes_facts_as_json() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _narrative_response(_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)
    facts = _facts()

    generator.generate(facts)

    _, kwargs = mock_client.messages.create.call_args
    user_content = kwargs["messages"][0]["content"]
    assert facts.model_dump_json(indent=2) in user_content


def test_generate_raises_narrative_parse_error_when_response_has_no_text_block() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(content=[])
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    try:
        generator.generate(_facts())
    except NarrativeParseError:
        pass
    else:
        raise AssertionError("expected NarrativeParseError when response has no text block")


def test_generate_raises_narrative_parse_error_on_oversized_bullets() -> None:
    """Reproduces the real production failure: a valid JSON response whose bullets
    list exceeds NoteNarrative's max_length=9 cap. Before #42's restructuring, this
    ValidationError happened inside messages.parse() and the raw model text that
    triggered it was unrecoverable -- this asserts that gap is closed."""
    fabricated_text = json.dumps(
        {
            "headline": "Yields Surge",
            "summary": "A very active session across rates.",
            "bullets": [f"Bullet point number {i}" for i in range(11)],
        }
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response(fabricated_text)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    try:
        generator.generate(_facts())
    except NarrativeParseError as exc:
        assert exc.raw_text == fabricated_text
    else:
        raise AssertionError("expected NarrativeParseError for an oversized bullet list")


def test_generate_raises_narrative_parse_error_on_malformed_json() -> None:
    fabricated_text = '{"headline": "Yields Surge", "summary": "Broken json'
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response(fabricated_text)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    try:
        generator.generate(_facts())
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

    narrative = generator.generate(_facts())

    assert narrative == expected


def test_generate_raises_narrative_parse_error_with_original_text_when_fence_recovery_fails() -> (
    None
):
    """A fenced-but-still-invalid response must still fail loudly, with the raw_text
    on the exception equal to the original (fenced) text, not the stripped attempt."""
    fabricated_text = '```json\n{"headline": "Yields Surge", "summary": "Broken\n```'
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _text_response(fabricated_text)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    try:
        generator.generate(_facts())
    except NarrativeParseError as exc:
        assert exc.raw_text == fabricated_text
    else:
        raise AssertionError("expected NarrativeParseError for a fenced but malformed response")


def test_narrative_generator_constructs_client_from_settings_when_omitted() -> None:
    # Constructing anthropic.Anthropic() only stores the key; it makes no network call.
    generator = NarrativeGenerator(settings=_settings())

    assert isinstance(generator._client, anthropic.Anthropic)
