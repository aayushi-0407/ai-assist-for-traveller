"""
Thin wrappers around whichever LLM provider a given call actually needs.
Two providers are wired up:

- Claude (Anthropic) via `ask_claude` — currently unusable, the project's
  Anthropic account has no billing credits (see PRD/README notes). Left in
  place for when that's resolved.
- Groq (fast, free-tier, OpenAI-compatible) via `ask_groq` — what
  reviews.get_best_seasons and agent0_best_time's specificity check
  actually use right now.

Keep provider clients instantiated here, not scattered across agents —
if you want to swap models, this is the one place to do it.
"""
import json
import re

from anthropic import Anthropic
from groq import Groq

from app.config import settings

_anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
_groq_client = Groq(api_key=settings.groq_api_key)


def ask_claude(prompt: str, model: str = "claude-sonnet-5", max_tokens: int = 1024) -> str:
    response = _anthropic_client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def ask_groq(
    prompt: str,
    model: str = "llama-3.3-70b-versatile",
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
