"""
Thin wrappers around the LLM providers used by the app.

For this project the active runtime path is Groq, because the Anthropic
account is not currently billable. We still keep the Anthropic client as an
optional helper, but the app prefers Groq to avoid invalid-key startup and
runtime failures when Anthropic is unavailable.
"""
import json
import re

from anthropic import Anthropic
from groq import Groq

from app.config import settings

_anthropic_client = (
    Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None
)
_groq_client = Groq(api_key=settings.groq_api_key)


def ask_question(
    prompt: str,
    model: str = "openai/gpt-oss-20b",
    max_tokens: int = 1024,
    temperature: float = 0.0,
    json_mode: bool = False,
) -> str:
    """Default LLM entry point for the app: always prefer Groq."""
    return ask_groq(
        prompt=prompt,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=json_mode,
    )


def ask_claude(prompt: str, model: str = "claude-sonnet-5", max_tokens: int = 1024) -> str:
    if _anthropic_client is None:
        return ask_question(prompt=prompt, max_tokens=max_tokens)

    try:
        response = _anthropic_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception:
        # If Anthropic is unavailable or invalid, fall back to Groq so the app
        # keeps working instead of crashing on an expired or missing key.
        return ask_question(prompt=prompt, max_tokens=max_tokens)


def ask_groq(
    prompt: str,
    model: str = "openai/gpt-oss-20b",
    max_tokens: int = 1024,
    temperature: float = 0.0,
    json_mode: bool = False,
) -> str:
    # temperature=0 by default: every current caller wants consistent
    # structured output, not creative variation.
    #
    # json_mode=True constrains the model to emit syntactically valid JSON.
    # Use it for every call whose result gets parsed — without it the model
    # occasionally emits malformed JSON (unterminated strings, stray prose)
    # and the parse blows up at runtime. Groq requires the word "JSON" to
    # appear in the prompt when this is on.
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = _groq_client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    return response.choices[0].message.content


def parse_llm_json(raw: str) -> dict:
    """Models sometimes wrap JSON in ```json fences or add a stray sentence
    before/after it even when told not to — this pulls out the first
    {...} block and parses that, instead of assuming `raw` is pure JSON."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response: {raw!r}")
    return json.loads(match.group(0))
