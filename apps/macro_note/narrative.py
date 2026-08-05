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

This module deliberately does not use messages.parse()/output_format. Two
consecutive real scheduled-run failures (one of them #44's bullets cap) showed
that when structured-output validation fails, the SDK discards the model's
raw text before the pydantic.ValidationError reaches calling code -- there is
no accessible hook to recover it (confirmed by reading anthropic's
lib/_parse/_response.py: the raw Message is a local variable inside the
post_parser closure, never attached to the exception). A prior version of this
module worked around that by manually rebuilding messages.parse()'s
output_config via anthropic's private, non-semver lib._parse._transform
module -- but investigation also showed that array max-length constraints
(e.g. NoteNarrative.bullets's max_length=9) are never forwarded into that
schema as a hard constraint anyway; the API rejects "maxItems" outright and
the SDK demotes it to descriptive text instead. So schema-constrained
decoding bought nothing against the actual failure mode, while adding a
fragile dependency on internals that could silently change on any anthropic
version bump. This module instead calls messages.create() directly, asks for
the JSON shape entirely via prompt instructions, and validates the returned
text into NoteNarrative itself -- so a validation failure can still log
exactly what the model wrote.
"""

import anthropic
import pydantic
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
        "Respond with a single JSON object and nothing else: no markdown code fences, no "
        "text before or after the JSON. The object must have exactly three fields: "
        '"headline" (a string), "summary" (a string), and "bullets" (an array of 1 to 9 '
        "strings). Do not include any other fields."
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


class NarrativeParseError(RuntimeError):
    """Raised when the model's response text did not validate into NoteNarrative.

    Carries the raw response text -- the one piece of information a bare
    pydantic.ValidationError discards -- so a parse failure can still be
    diagnosed from the logs instead of leaving only a shape mismatch.
    """

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


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
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(facts)}],
        )
        text = _extract_text(response)

        candidates = [text]
        unfenced = _strip_code_fence(text)
        if unfenced is not None:
            candidates.append(unfenced)

        last_error: pydantic.ValidationError | None = None
        for candidate in candidates:
            try:
                return NoteNarrative.model_validate_json(candidate)
            except pydantic.ValidationError as exc:
                last_error = exc

        raise NarrativeParseError(
            f"Model response did not validate into NoteNarrative: {last_error}",
            raw_text=text,
        ) from last_error


def _extract_text(response: anthropic.types.Message) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    raise NarrativeParseError(
        "Anthropic response contained no text block", raw_text=str(response.content)
    )


def _strip_code_fence(text: str) -> str | None:
    """Strips a single wrapping ``` or ```json code fence, or returns None if
    `text` isn't fenced.

    The prompt explicitly asks for no fences, but wrapping JSON in a markdown
    code block is a common enough model habit that it's worth recovering from
    before failing the run over otherwise-valid content -- unlike a genuine
    content violation (e.g. too many bullets), a fence is a cosmetic artifact
    around the JSON, not a data-integrity problem. This is tried only as a
    fallback after the raw text fails to parse; see generate().
    """
    stripped = text.strip()
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return None


def _build_prompt(facts: NoteFacts) -> str:
    return (
        "Today's computed macro metrics, as JSON. Write the note narrative "
        f"based only on these figures.\n\n{facts.model_dump_json(indent=2)}"
    )
