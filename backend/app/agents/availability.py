"""
Agents 1 and 2's *search* halves, run jointly and up front.

This is one graph node rather than two because their outputs have to
describe the same trip: a flight window with no matching hotel inventory
isn't a partial answer, it's a wrong one. The reconciliation logic lives
in services/availability.py; this file only reads TripState and writes the
result back.

It runs in PARALLEL with agent3_build (see orchestrator.py) — three agents
working the shortlist at once, each on something the others don't need:

    agent0_choose
       ├─> agent3_build     itinerary per shortlisted destination
       └─> availability     flights + hotels + a window they agree on
             both join at ─> agent3_choose

So by the time the user compares destinations, each card carries a real
itinerary, a real total price and dates that are actually bookable —
rather than an itinerary now and an unpleasant surprise two steps later.

WHAT THIS NODE DOES NOT DO: book anything. Searching all shortlisted
destinations is cheap and reversible; booking one the user then rejects is
neither. Agent 1's booking stays after the destination is locked in
(PRD section 8), reading the options this node already found.
"""
import logging
from typing import Any, Dict

from app.services import availability as availability_service
from app.services import budget as budget_service

logger = logging.getLogger(__name__)


def _starting_windows(state: Dict) -> Dict[str, Dict[str, str]]:
    """Where each destination's hunt begins.

    With flexible dates that's the window research picked for that
    specific place — the whole point of a flexible window is that the best
    week differs per destination. With fixed dates every destination
    starts, and stays, on the window the user committed to.
    """
    shortlisted = state["shortlisted_destinations"]
    fixed = state.get("date_mode") == "fixed"
    agreed = state.get("selected_date_window")

    by_name = {c["name"]: c for c in state.get("candidate_destinations") or []}
    windows = {}
    for name in shortlisted:
        candidate = by_name.get(name)
        if fixed or not candidate:
            windows[name] = agreed
        else:
            windows[name] = {"start": candidate["start"], "end": candidate["end"]}
    return windows


def search_all(state: Dict) -> Dict:
    """Find, for every shortlisted destination, a window that's bookable."""
    results = availability_service.for_destinations(
        destinations=state["shortlisted_destinations"],
        origin=state["origin"],
        windows=_starting_windows(state),
        travellers=state.get("travellers", 1),
        allocation=state["budget_allocation"],
        budget_total=state["budget_total"],
        # Never move dates the user pinned themselves — see the module
        # docstring in services/availability.py.
        shiftable=state.get("date_mode") != "fixed",
    )

    for name, r in results.items():
        logger.info(
            "availability %s: available=%s window=%s shifted=%s blocked_by=%s total=%s",
            name, r["available"], r.get("window"), r.get("shifted_by"),
            r.get("blocked_by"), r.get("trip_total"),
        )

    return {"availability": results}


def carry_forward(state: Dict) -> Dict:
    """Move the chosen destination's pre-searched results into the fields
    Agents 1 and 2 read.

    Deliberately re-reads what `search_all` already found instead of
    searching again: those offer IDs are what the user was shown a price
    for, and Duffel hands back new IDs at new prices on every call.

    Also pins `selected_date_window` to the reconciled window rather than
    whatever Agent 0 guessed — this is the point where the trip's dates
    become the ones that are actually bookable on both sides.
    """
    chosen = state["resolved_destination"]
    found: Dict[str, Any] = (state.get("availability") or {}).get(chosen) or {}

    updates: Dict[str, Any] = {
        "flight_options": found.get("flights") or [],
        "hotel_options": found.get("hotels") or [],
    }
    if found.get("window"):
        updates["selected_date_window"] = found["window"]

    # The initial split was guessed before anything was priced, so a trip
    # that fits the total can still blow a single slice. Move the money
    # before asking the user for more of it — otherwise the comparison card
    # says "fits your budget" and the very next step says it doesn't.
    rebalanced = budget_service.reallocate(
        state["budget_allocation"],
        state["budget_total"],
        found.get("cheapest_flight"),
        found.get("hotel_total"),
    )
    if rebalanced:
        logger.info(
            "reallocated for %s: %s -> %s", chosen, state["budget_allocation"], rebalanced
        )
        updates["budget_allocation"] = rebalanced

    return updates
