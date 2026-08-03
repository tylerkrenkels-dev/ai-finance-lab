"""Turns a NoteFacts payload into prose via exactly one Anthropic API call.

The model receives already-computed, validated figures and writes prose about
them. It never computes, estimates, infers, or restates a figure that is not
already in NoteFacts -- that invariant is instructed here and mechanically
enforced downstream by the numeric fidelity guard.

SYSTEM_PROMPT's digit-form instruction (numbers must appear as "2", never
spelled out as "two") is a best-effort nudge, not a guarantee. Live testing
showed claude-haiku-4-5 at temperature=0 following it in some output fields
(bullets) but not others (summary) for the same fact in the same response --
a prompt instruction is not mechanical enforcement. The guard in #20 must
independently verify every numeral in the output against NoteFacts regardless
of what this prompt asks for, and must itself recognize both digit and common
spelled-out small-number forms (at minimum one through twenty) as valid
matches -- not assume the prompt's instruction was followed.
"""

import anthropic
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.macro_note.models import NoteFacts, NoteNarrative

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1024

_PARAGRAPHS = [
    (
        "You are a financial writer producing the prose for a daily macro research note. "
        "You will be given a JSON payload of already-computed metrics: prices, percentage "
        "changes, basis-point changes, curve slopes, and FX carry figures. Every number in "
        "that payload has already been calculated and validated by other software before "
        "it reached you."
    ),
    (
        "Your job is to write prose that describes and contextualizes these figures: a "
        "headline, a summary, and bullet points. You may reference any number that already "
        "appears in the payload, exactly as it appears there."
    ),
    (
        "You must never calculate, estimate, infer, interpolate, round differently, "
        "average, or otherwise produce a number that is not already present in the "
        "payload. This includes simple-seeming arithmetic, such as a difference between "
        "two figures or a rate of change between two dates. If a comparison would require "
        "arithmetic you have not been given the result of, describe the relationship in "
        'words only (for example "widened," "narrowed," "outpaced") without stating a '
        "new number."
    ),
    (
        "Numbers you do use from the payload must be reproduced exactly as given, not "
        "re-rounded or reformatted for readability. For example, a value of 4.25% must "
        'appear as "4.25%", never as "4.3%" or "about 4.25%". Do not adjust precision, '
        "add or drop trailing digits, or paraphrase a figure into an approximation, even "
        "if the exact figure looks awkward in a sentence. Numbers must always be written "
        "in digit form exactly as they appear in the payload, never spelled out as words "
        '(for example "2," never "two").'
    ),
    (
        "If the payload's data_warnings list is non-empty, mention any staleness or "
        "missing data using only the information given in that list. Do not invent your "
        "own explanation for why data is stale or missing, and do not guess at a value "
        "that is missing."
    ),
    (
        "Write in a neutral, professional register suitable for institutional readers. "
        "Do not use markdown formatting in your output fields."
    ),
]

SYSTEM_PROMPT = "\n\n".join(_PARAGRAPHS)


class AnthropicSettings(BaseSettings):
    """Anthropic API credentials, read from .env. Never hardcoded."""

    anthropic_api_key: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class NarrativeGenerator:
    """Generates a NoteNarrative from a NoteFacts payload via the Anthropic API."""

    def __init__(
        self,
        settings: AnthropicSettings | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        # mypy sees anthropic_api_key as a required constructor arg; pydantic-settings
        # actually supplies it from the environment/.env at runtime.
        self._settings = settings or AnthropicSettings()  # type: ignore[call-arg]
        self._client = client or anthropic.Anthropic(api_key=self._settings.anthropic_api_key)

    def generate(self, facts: NoteFacts) -> NoteNarrative:
        """Call the Anthropic API once, turning `facts` into a NoteNarrative."""
        response = self._client.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(facts)}],
            output_format=NoteNarrative,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError("Anthropic response did not parse into a NoteNarrative")
        return parsed


def _build_prompt(facts: NoteFacts) -> str:
    return (
        "Today's computed macro metrics, as JSON. Write the note narrative "
        f"based only on these figures.\n\n{facts.model_dump_json(indent=2)}"
    )
