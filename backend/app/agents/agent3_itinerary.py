"""
Agent 3 — Itinerary Builder + destination decision (PRD section 7)

Runs BEFORE flights/hotels (see orchestrator.py): the user compares real
day-by-day plans across their shortlisted destinations and only then locks
one in. That locked destination is what Agent 1 and Agent 2 book against.

Two graph nodes, same search/pause split as the other agents:

  build  : one itinerary per shortlisted destination (real LLM calls).
  choose : [interrupt] user compares them and picks the winner.

Splitting matters here for the usual replay-safety reason — `build` is
non-deterministic, so it has to be checkpointed before `choose` pauses, or
a resume could show the user one plan and lock in another. See
agent1_flights.py's docstring for the full explanation.
"""
from typing import Any, Dict, List

from langgraph.types import interrupt

from app.agents import offscript
from app.services import nlu
from app.services.llm import ask_groq, parse_llm_json


# How full a day should feel, read off how the user divided their budget
# at Agent 0's intake (see services/budget.style_from_preference). Someone
# who put their money into the hotel did not ask for a packed schedule.
_PACE = {
    "relaxation": (
        "They're spending more on where they stay than on what they do, so "
        "keep days unhurried — 2 places at most, with real time at each, and "
        "leave room to do nothing."
    ),
    "activities": (
        "They're spending more on what they do than on where they stay, so "
        "fill the days — 3 to 4 places, and favour things worth paying for "
        "over places you simply walk past."
    ),
    "balanced": "Aim for 2 to 4 places per day.",
}


def _build_one(
    destination: str, days: int, budget: float, travellers: int, style: str
) -> List[Dict[str, Any]]:
    prompt = (
        f"Build a {days}-day travel itinerary for {destination}.\n\n"
        f"Budget for activities and food across the whole trip: {budget:.0f} "
        f"for {travellers} traveller(s). The plan should be realistic, with "
        "each day's places grouped near each other (they'll be routed by a "
        "maps API afterwards).\n\n"
        f"{_PACE.get(style, _PACE['balanced'])}\n\n"
        "Use real, specific, named places that exist in or near "
        f"{destination} — no generic entries like 'local market'.\n\n"
        "Respond with ONLY JSON:\n"
        '{"days": [{"day": 1, "title": "<short theme for the day>", '
        '"places": ["<real place name>", ...], "est_cost": <number>}]}'
    )
    raw = ask_groq(prompt, json_mode=True, max_tokens=2048)
    return parse_llm_json(raw)["days"]


def build(state: Dict) -> Dict:
    days = state.get("trip_days") or 7
    budget = state["budget_allocation"]["itinerary"]
    travellers = state.get("travellers", 1)
    style = state.get("trip_style") or "balanced"

    itineraries = {
        destination: _build_one(destination, days, budget, travellers, style)
        for destination in state["shortlisted_destinations"]
    }
    return {"itinerary_options": itineraries}


def _bookable(state: Dict, destination: str) -> bool:
    """Did the availability branch find a window with both flights and rooms?

    A destination that didn't is still shown — its itinerary is real and
    worth seeing — but it can't be picked, because everything downstream
    assumes there is something to book.
    """
    found = (state.get("availability") or {}).get(destination) or {}
    return bool(found.get("available"))


def _unavailable_note(state: Dict, destination: str) -> str:
    """Explain, in the user's terms, which half was missing."""
    found = (state.get("availability") or {}).get(destination) or {}
    window = found.get("window") or {}
    dates = f"{window.get('start')} to {window.get('end')}" if window else "those dates"
    reason = {
        "hotels": f"I found flights for {destination} but nowhere to stay",
        "flights": f"I found places to stay in {destination} but no flights",
        "both": f"I couldn't find flights or rooms for {destination}",
        "error": f"Something went wrong looking up {destination}",
    }.get(found.get("blocked_by"), f"{destination} isn't bookable")

    tried = len(found.get("windows_tried") or [])
    shifted = (
        f" I tried {tried} different weeks around {dates}."
        if tried > 1
        else f" I looked at {dates}."
    )
    return f"{reason}.{shifted} Pick one of the others, or change your dates."


def choose(state: Dict) -> Dict:
    """Compare the itineraries — with real prices and real dates — and lock
    in the destination for booking.

    By the time this runs, both parallel branches have finished: Agent 3
    has an itinerary per destination and the availability branch has, for
    each one, a window where flights and hotels both exist plus what the
    whole thing costs. Comparing on that is the entire point of running
    them together — a day-by-day plan the user can't afford, or can't get
    a room for, isn't a real option to choose between.
    """
    options = state["itinerary_options"]
    names = list(options.keys())
    bookable = [n for n in names if _bookable(state, n)]

    def payload() -> Dict[str, Any]:
        return {
            "itineraries": options,
            "date_window": state["selected_date_window"],
            # Per-destination window, prices and fit — see state.availability.
            "availability": state.get("availability") or {},
            "bookable": bookable,
        }

    # Nothing to compare — skip the pause rather than making the user
    # "choose" from a list of one. Only safe when that one is bookable;
    # otherwise they need to be told, not silently marched into a dead end.
    if len(names) == 1 and bookable == names:
        winner = names[0]
        return {"resolved_destination": winner, "itinerary": options[winner]}

    question = (
        "Here's how each option actually looks day by day, with what it "
        "costs and the dates I can actually get. Which one do you want?"
    )
    note = None

    while True:
        reply = interrupt({
            "stage": "agent3_choose",
            "text": f"{note}\n\n{question}" if note else question,
            "data": payload(),
        })
        kind, offscript_payload = offscript.triage(reply, state, question)
        if kind == "restart":
            return offscript_payload
        if kind == "note":
            note = offscript_payload
            continue

        winner = nlu.parse_itinerary_choice(
            reply.get("message", ""), names, reply.get("selection")
        )
        if winner and winner in bookable:
            break
        # Picking an unbookable destination is a real choice, not a parse
        # failure — say why it can't be honoured instead of re-asking blankly.
        note = _unavailable_note(state, winner) if winner else None

    return {"resolved_destination": winner, "itinerary": options[winner]}
