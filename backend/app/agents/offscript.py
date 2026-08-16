"""
Shared off-script handling for every stage that takes a free-text reply.

Each interrupt loop calls `triage()` right after `interrupt()` returns. It
gives back one of:

  ("answer", None)      -> fall through to the stage's own parser
  ("note", "<text>")    -> the reply was a question; show this answer and
                           ask the stage's question again
  ("restart", {...})    -> the user changed where they want to go; return
                           this dict from the node and the conditional
                           edge in orchestrator.py routes back to Agent 0

The restart is a plain state update read by a conditional edge, NOT a
`Command(goto=...)` returned from the node. Returning a goto from a node
that is itself mid-interrupt re-enters that node with the same resume
value still pending, which ping-pongs and lets the wrong branch run.
Ordinary edges keep the routing well defined.

Centralised so all stages behave the same way — a question shouldn't be
answerable at one step and silently mis-parsed at another.
"""
from typing import Any, Dict, Optional, Tuple

from app.services import conversation


def triage(
    reply: Dict[str, Any],
    state: Dict[str, Any],
    question: str,
) -> Tuple[str, Optional[Any]]:
    message = (reply.get("message") or "").strip()

    # A click is unambiguous — never second-guess it.
    if reply.get("selection") or not message:
        return ("answer", None)

    intent = conversation.classify(message, question)["intent"]

    if intent == "question":
        return ("note", conversation.answer_question(message, state))

    if intent == "new_criteria":
        # `restart_query` is the signal the conditional edges look for.
        # Stale results from the previous criteria are cleared so a
        # half-updated shortlist can't leak into the next step.
        return (
            "restart",
            {
                "restart_query": message,
                "candidate_destinations": [],
                "shortlisted_destinations": [],
                "itinerary_options": {},
            },
        )

    return ("answer", None)


def is_restarting(state: Dict[str, Any]) -> str:
    """Conditional-edge predicate: did the last reply ask for different
    destinations entirely?"""
    return "research" if state.get("restart_query") else "next"
