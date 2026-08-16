"""
Handling for messages that don't answer the question that was asked.

Without this, every stage force-fits whatever the user typed into the
answer it was expecting. Asking "can I see snowfall in Darjeeling?" while
being asked for a departure city got parsed as an origin of *Darjeeling* —
the trip then silently booked flights out of the wrong airport.

So every free-text reply is classified first:

  answer        -> the stage's own parser handles it (normal path)
  question      -> answer it, then ask the stage's question again
  new_criteria  -> the user changed their mind about where they're going;
                   the graph jumps back to Agent 0 to research afresh

`selection` payloads (a click) skip all of this — a click is unambiguous.
"""
from typing import Any, Dict

from app.services.llm import ask_groq, parse_llm_json


def classify(message: str, current_question: str) -> Dict[str, Any]:
    """Work out whether a reply answers the question, asks one, or changes
    the trip's requirements."""
    prompt = (
        "A travel assistant asked the user a question. Classify what the "
        "user's reply is actually doing.\n\n"
        f"Assistant asked: {current_question!r}\n"
        f"User replied: {message!r}\n\n"
        "Categories:\n"
        '- "answer": replying to the question that was asked, even loosely '
        "or partially.\n"
        '- "question": asking the assistant something instead of answering '
        "(about weather, a place, what's possible, etc).\n"
        '- "new_criteria": stating a different or additional requirement for '
        "WHERE they want to go — a new kind of destination, scenery, "
        "activity or season. This means the destination shortlist needs "
        "redoing, not that they answered.\n\n"
        "Rules that decide the tricky cases:\n"
        "- Naming a place inside a question (\"can I see snow in "
        "Darjeeling?\") is a QUESTION, not an answer.\n"
        "- Picking, comparing or instructing about options that were just "
        'offered is an ANSWER, even phrased as a command ("compare Shillong '
        'and Gangtok", "show me both", "book the cheapest").\n'
        "- Only use new_criteria when they want DIFFERENT destinations than "
        "the ones on the table, not when narrowing between them.\n\n"
        'Respond with ONLY JSON: {"intent": "answer" | "question" | "new_criteria"}'
    )
    result = parse_llm_json(ask_groq(prompt, json_mode=True))
    intent = result.get("intent")
    return {"intent": intent if intent in {"answer", "question", "new_criteria"} else "answer"}


def answer_question(message: str, state: Dict[str, Any]) -> str:
    """Answer a travel question, given what the trip already knows.

    Kept to a couple of sentences: this is an aside inside a booking flow,
    and the stage's own question gets re-asked straight after it.
    """
    context_bits = []
    if state.get("resolved_destination"):
        context_bits.append(f"chosen destination: {state['resolved_destination']}")
    elif state.get("shortlisted_destinations"):
        context_bits.append(f"shortlisted: {', '.join(state['shortlisted_destinations'])}")
    if state.get("selected_date_window"):
        window = state["selected_date_window"]
        context_bits.append(f"travelling {window['start']} to {window['end']}")

    prompt = (
        "Answer this traveller's question in at most two short sentences. "
        "Be concrete and honest — if something is unlikely (e.g. snow in a "
        "place that rarely gets it), say so and name a better alternative.\n\n"
        + (f"Trip so far: {'; '.join(context_bits)}\n" if context_bits else "")
        + f"Question: {message!r}"
    )
    return ask_groq(prompt, max_tokens=200).strip()
