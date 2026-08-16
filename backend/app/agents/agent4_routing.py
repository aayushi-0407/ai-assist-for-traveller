"""
Agent 4 — Route Optimization / Google Maps integration (PRD section 7)

Input: itinerary (from Agent 3 — day plans, each with a list of places)
Output: routed_itinerary (same shape, places reordered + travel legs)

Runs right after the destination is locked in, so the winning itinerary is
route-optimised before the user moves on to booking.
"""
from typing import Dict

from app.services import maps_api


def run(state: Dict) -> Dict:
    destination = state["resolved_destination"]

    routed = []
    for day in state["itinerary"]:
        places = day["places"]
        if len(places) < 2:
            routed.append({**day, "route_legs": []})
            continue

        # Qualify bare place names with the destination before geocoding —
        # "Ward's Lake" alone is ambiguous worldwide, "Ward's Lake, Shillong"
        # is not. The qualified form is only used for the lookup; the UI
        # keeps showing the original names.
        qualified = [f"{p}, {destination}" for p in places]
        ordered_qualified, legs = maps_api.optimize_route(qualified)

        order = [qualified.index(q) for q in ordered_qualified]
        ordered_places = [places[i] for i in order]
        for leg, from_i, to_i in zip(legs, order, order[1:]):
            leg["from"] = places[from_i]
            leg["to"] = places[to_i]

        routed.append({**day, "places": ordered_places, "route_legs": legs})

    return {"routed_itinerary": routed}
