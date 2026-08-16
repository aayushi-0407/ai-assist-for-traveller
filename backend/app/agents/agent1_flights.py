"""
Agent 1 — Flight Search & Booking (PRD section 7)

Agent 1's *search* half no longer lives here. It runs up front, in
parallel with Agent 3 and jointly with Agent 2, because flight dates and
hotel dates have to agree before either is worth showing — see
agents/availability.py and services/availability.py.

What's left is everything that must happen AFTER the user locks a
destination, plus the one question search itself depends on:

  ask_origin       : [interrupt] fallback only — Agent 0's intake requires
                     an origin, so this normally no-ops. Sits before the
                     fan-out, since availability can't search without it.
  raise_budget     : [interrupt] nothing affordable; ask for a bigger slice.
  approve_and_book : [interrupt] user picks an option, then it books.

--------------------------------------------------------------------------
WHY BOOKING NEVER RE-SEARCHES:

LangGraph replays a node's code from the top on every resume from
interrupt(), and flights_api.search() is a real, non-deterministic API
call — each call returns fresh offer IDs and slightly different prices for
the same query. So `approve_and_book` reads the `flight_options` the
availability branch already persisted (via availability.carry_forward)
rather than searching again. Put a search back into this node and resuming
after the user picks an option would silently re-search, get new offer
IDs, and either fail to find the picked ID or — worse — book something
other than what they were shown.

The same reasoning is why `ask_budget` was removed rather than moved: the
budget split is collected by Agent 0's intake (criterion 4), and asking
again here couldn't affect a search that has already run.
--------------------------------------------------------------------------
"""
from typing import Dict, List

from langgraph.types import interrupt

from app.agents import offscript
from app.services import flights_api, nlu


def ask_origin(state: Dict) -> Dict:
    """Fallback only, since Agent 0's intake now requires an origin.

    Runs before the parallel fan-out rather than after the destination is
    picked, because availability search can't start without a departure
    city. Kept despite intake guaranteeing one because the graph can
    re-enter this path after a mid-flow change of destination, and because
    `origins` may hold several departure cities while this agent still
    prices a single route — see intake.primary_origin for which one.
    """
    if state.get("origin"):
        return {}

    # Phrased against the shortlist, not a resolved destination: at this
    # point in the graph the user hasn't picked one yet.
    shortlist = state.get("shortlisted_destinations") or []
    where = " and ".join(shortlist) if shortlist else "your trip"
    question = f"To price {where}, which city are you flying from?"
    note = None

    while True:
        reply = interrupt({
            "stage": "agent1_origin",
            "text": f"{note}\n\n{question}" if note else question,
            "data": {},
        })
        kind, payload = offscript.triage(reply, state, question)
        if kind == "restart":
            return payload
        if kind == "note":
            note = payload
            continue

        origin = nlu.parse_origin(reply.get("message", ""), reply.get("selection"))
        if origin:
            break
        note = None

    return {"origin": origin}


def affordable(state: Dict) -> List[Dict]:
    return [o for o in state["flight_options"] if o["price"] <= state["budget_allocation"]["flights"]]


def needs_more_budget(state: Dict) -> str:
    """Conditional edge: nothing within budget means ask for more rather
    than showing options the user can't afford."""
    return "raise_budget" if state["flight_options"] and not affordable(state) else "approve"


def raise_budget(state: Dict) -> Dict:
    """Nothing fit the flight budget — tell the user what it actually costs
    and let them raise it.

    The graph then loops back to availability_carry, which re-filters the
    same persisted options against the new figure. It does NOT re-search:
    the prices didn't change, only what the user is willing to pay, and a
    fresh Duffel call would invalidate every offer ID already on screen.
    """
    options = state["flight_options"]
    cheapest = min(o["price"] for o in options)
    currency = options[0].get("currency", "")
    allocated = state["budget_allocation"]["flights"]

    while True:
        reply = interrupt({
            "stage": "agent1_budget_short",
            "text": (
                f"Nothing fits the {allocated:,.0f} set aside for flights — the "
                f"cheapest I can find is {cheapest:,.0f} {currency}. How much can "
                "you spend on flights?"
            ),
            "data": {
                "allocated": allocated,
                "cheapest": cheapest,
                "currency": currency,
                "suggested": cheapest,
            },
        })
        override = nlu.parse_budget_split(
            reply.get("message", ""), state["budget_allocation"], reply.get("selection")
        )
        if override.get("flights"):
            break

    return {"budget_allocation": {**state["budget_allocation"], "flights": float(override["flights"])}}


def approve_and_book(state: Dict) -> Dict:
    options = affordable(state)
    # Fields prefixed with "_" are internal booking plumbing — strip them
    # rather than leak them into the UI payload.
    public = [{k: v for k, v in o.items() if not k.startswith("_")} for o in options]

    question = "Here are the flights I found. Which one should I book?"

    # Agent 0 can capture several departure cities, but this agent still
    # prices one route (the largest group's). Say so rather than letting
    # the user assume the total covers everyone.
    unpriced = [o for o in state.get("origins") or [] if o["city"] != state.get("origin")]
    if unpriced:
        others = ", ".join(f"{o['travellers']} from {o['city']}" for o in unpriced)
        question += (
            f" These are from {state['origin']} only — I haven't priced the "
            f"{others} leg yet."
        )

    note = None

    while True:
        reply = interrupt({
            "stage": "agent1_approve",
            "text": f"{note}\n\n{question}" if note else question,
            "data": {"flights": public, "budget": state["budget_allocation"]["flights"]},
        })
        kind, payload = offscript.triage(reply, state, question)
        if kind == "restart":
            return payload
        if kind == "note":
            note = payload
            continue

        chosen_id = nlu.parse_option_choice(
            reply.get("message", ""), public, "carrier", reply.get("selection")
        )
        if chosen_id:
            break
        note = None

    chosen = next(o for o in state["flight_options"] if o["id"] == chosen_id)
    booking = flights_api.book(chosen)

    return {
        "booked_flight": booking,
        "budget_remaining": state["budget_remaining"] - booking["price"],
    }
