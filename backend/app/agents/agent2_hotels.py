"""
Agent 2 — Hotel Search & Deep-Link Booking (PRD section 7)

Agent 2's *search* half now runs up front, jointly with Agent 1's, because
a hotel found for one set of dates and a flight found for another don't
describe a trip anyone can take. See services/availability.py for the
reconciliation, and agents/availability.py for the node.

What's left here is the pick, plus the budget escape hatch: if nothing is
available within the hotel slice, the graph diverts to `raise_budget` and
comes back once the user raises it, rather than showing rooms they can't
afford. Like Agent 1, that loop re-filters the already-persisted options
instead of re-searching.

Unlike Agent 1 there's no book() call: no hotel provider offers instant
self-serve booking access (PRD section 12), so the user's pick just
carries a deep link they finish the booking on.
"""
from datetime import date
from typing import Dict, List

from langgraph.types import interrupt

from app.agents import offscript
from app.services import nlu


def _nights(state: Dict) -> int:
    window = state.get("selected_date_window") or {}
    if not window.get("start") or not window.get("end"):
        return 1
    return max(
        1,
        (date.fromisoformat(window["end"]) - date.fromisoformat(window["start"])).days,
    )


def affordable(state: Dict) -> List[Dict]:
    """Rooms whose WHOLE-STAY cost fits the hotel slice.

    SerpApi quotes per night while the budget slice covers the trip, so
    comparing the two directly made a 5-night stay look five times more
    affordable than it is.
    """
    nights = _nights(state)
    budget = state["budget_allocation"]["hotel"]
    return [o for o in state["hotel_options"] if o["price"] * nights <= budget]


def needs_more_budget(state: Dict) -> str:
    """Conditional edge: nothing within budget means ask for more rather
    than showing rooms the user can't afford."""
    return "raise_budget" if state["hotel_options"] and not affordable(state) else "approve"


def raise_budget(state: Dict) -> Dict:
    options = state["hotel_options"]
    nights = _nights(state)
    cheapest_night = min(o["price"] for o in options)
    cheapest = round(cheapest_night * nights, 2)
    allocated = state["budget_allocation"]["hotel"]

    while True:
        reply = interrupt({
            "stage": "agent2_budget_short",
            "text": (
                f"Nothing fits the {allocated:,.0f} set aside for the stay — the "
                f"cheapest room I can find is {cheapest_night:,.0f} a night, "
                f"{cheapest:,.0f} across {nights} night(s). How much can you "
                "spend on the stay?"
            ),
            "data": {
                "allocated": allocated,
                "cheapest": cheapest,
                "suggested": cheapest,
                "nights": nights,
                "per_night": cheapest_night,
            },
        })
        override = nlu.parse_budget_split(
            reply.get("message", ""), state["budget_allocation"], reply.get("selection")
        )
        if override.get("hotel"):
            break

    return {"budget_allocation": {**state["budget_allocation"], "hotel": float(override["hotel"])}}


def approve(state: Dict) -> Dict:
    options = affordable(state)

    question = "Pick a hotel and I'll give you the link to finish booking."
    note = None

    while True:
        reply = interrupt({
            "stage": "agent2_approve",
            "text": f"{note}\n\n{question}" if note else question,
            # `nights` so the UI can show the whole-stay cost next to the
            # nightly rate — the budget is a trip figure, the rate isn't.
            "data": {
                "hotels": options,
                "budget": state["budget_allocation"]["hotel"],
                "nights": _nights(state),
            },
        })
        kind, payload = offscript.triage(reply, state, question)
        if kind == "restart":
            return payload
        if kind == "note":
            note = payload
            continue

        chosen_id = nlu.parse_option_choice(
            reply.get("message", ""), options, "name", reply.get("selection")
        )
        if chosen_id:
            break
        note = None

    chosen = next(o for o in state["hotel_options"] if o["id"] == chosen_id)

    return {
        "selected_hotel": chosen,
        # Draw down the whole stay, not one night — otherwise the running
        # total says the trip cost a fraction of what it did.
        "budget_remaining": state["budget_remaining"] - chosen["price"] * _nights(state),
    }
