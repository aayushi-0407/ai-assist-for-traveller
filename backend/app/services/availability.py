"""
Joint flight + hotel availability, reconciled onto a single date window.

Agents 1 and 2 search independently everywhere else in this codebase, and
that is fine right up until their answers have to describe the same trip.
A flight on 1 Aug returning 7 Aug is worthless if nothing has a room those
nights, so the two searches cannot each pick their own dates — they have
to agree on one window, or the "plan" is two half-plans that don't meet.

So this module owns the reconciliation:

    for each destination:
        for each candidate window (the researched one, then shifts):
            search flights and hotels FOR THAT SAME WINDOW, in parallel
            if both came back with something -> done, that's the window
        otherwise -> report which side was missing, so the user is told
                     *why* rather than just seeing an empty list

Two hard rules:

1. **A window is only usable if both sides have inventory.** Half a match
   is a miss. Returning flights-only would let the pipeline carry a
   destination the user cannot actually stay in.

2. **Fixed dates are never shifted.** If the user committed to specific
   dates at intake (date_mode == "fixed"), moving them to find inventory
   silently rebooks their trip around the hotel market. They get told the
   clash instead. Shifting is only for a flexible window, where the exact
   week was ours to choose in the first place.

Probe budget is deliberately small (MAX_PROBES): each probe costs one
SerpApi call per destination and that tier allows 100 searches a month, so
an unbounded hunt would burn it on a single plan. See PROBE_OFFSETS.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from app.services import flights_api, hotels_api

logger = logging.getLogger(__name__)

# Tried in order, as day offsets applied to both ends of the window at
# once (so the trip keeps its length). 0 first: the window research picked
# is the seasonally right one, and we only move off it under duress.
PROBE_OFFSETS = (0, -3, 3, -6, 6)
MAX_PROBES = 3

# Availability is only searched for the first few shortlisted places.
# Beyond that the API cost per plan climbs faster than the comparison gets
# more useful — nobody meaningfully compares six trips.
MAX_DESTINATIONS = 3


def _shift(window: Dict[str, str], days: int) -> Dict[str, str]:
    """Move both ends of a window, preserving its length."""
    start = date.fromisoformat(window["start"]) + timedelta(days=days)
    end = date.fromisoformat(window["end"]) + timedelta(days=days)
    return {"start": start.isoformat(), "end": end.isoformat()}


def _nights(window: Dict[str, str]) -> int:
    return max(1, (date.fromisoformat(window["end"]) - date.fromisoformat(window["start"])).days)


def _in_the_past(window: Dict[str, str]) -> bool:
    return date.fromisoformat(window["start"]) <= date.today()


def _probe(
    destination: str, origin: str, window: Dict[str, str], travellers: int
) -> Dict[str, Any]:
    """One window, both sides, searched at the same time.

    Flights and hotels are independent network calls against different
    providers, so running them concurrently roughly halves the wall clock
    of a probe — and a probe is the unit this whole module repeats.

    Each side is caught separately: an origin with no resolvable airport
    (flights_api raises) shouldn't hide the fact that hotels were fine, and
    vice versa. The caller needs to know *which* side was empty to explain
    it to the user.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        flight_job = pool.submit(
            flights_api.search, origin, destination, window, travellers
        )
        hotel_job = pool.submit(hotels_api.search, destination, window, travellers)

        try:
            flights = flight_job.result()
            flight_error = None
        except Exception as exc:                       # noqa: BLE001 - reported, not raised
            logger.warning("Flight search failed for %s %s: %s", destination, window, exc)
            flights, flight_error = [], str(exc)

        try:
            hotels = hotel_job.result()
            hotel_error = None
        except Exception as exc:                       # noqa: BLE001 - reported, not raised
            logger.warning("Hotel search failed for %s %s: %s", destination, window, exc)
            hotels, hotel_error = [], str(exc)

    return {
        "window": window,
        "flights": flights,
        "hotels": hotels,
        "flight_error": flight_error,
        "hotel_error": hotel_error,
    }


def _blocker(probe: Dict[str, Any]) -> Optional[str]:
    """Which side stopped this window being usable, if either."""
    if not probe["flights"] and not probe["hotels"]:
        return "both"
    if not probe["flights"]:
        return "flights"
    if not probe["hotels"]:
        return "hotels"
    return None


def _priced(
    probe: Dict[str, Any], travellers: int, allocation: Dict[str, float], budget_total: float
) -> Dict[str, Any]:
    """Cost the cheapest workable combination for this window.

    Flight prices already cover the whole party (flights_api sends one
    passenger per traveller). Hotel rates are per night for the room, so
    they're multiplied out across the stay — comparing a nightly rate
    against a whole-trip hotel budget is the easiest way to make an
    unaffordable trip look fine.
    """
    nights = _nights(probe["window"])
    cheapest_flight = min((f["price"] for f in probe["flights"]), default=None)
    cheapest_hotel_night = min((h["price"] for h in probe["hotels"]), default=None)
    hotel_total = cheapest_hotel_night * nights if cheapest_hotel_night is not None else None

    trip_total = None
    if cheapest_flight is not None and hotel_total is not None:
        trip_total = round(cheapest_flight + hotel_total, 2)

    return {
        "nights": nights,
        "cheapest_flight": cheapest_flight,
        "cheapest_hotel_night": cheapest_hotel_night,
        "hotel_total": round(hotel_total, 2) if hotel_total is not None else None,
        "trip_total": trip_total,
        "flights_fit": (
            cheapest_flight is not None and cheapest_flight <= allocation["flights"]
        ),
        "hotel_fits": hotel_total is not None and hotel_total <= allocation["hotel"],
        "fits_budget": trip_total is not None and trip_total <= budget_total,
    }


def for_destination(
    destination: str,
    origin: str,
    window: Dict[str, str],
    travellers: int,
    allocation: Dict[str, float],
    budget_total: float,
    shiftable: bool,
) -> Dict[str, Any]:
    """Find a window this destination is actually bookable in.

    Returns the first window where flights AND hotels both have inventory,
    with everything priced. If no probe finds one, returns the best attempt
    plus `blocked_by` so the caller can say which half was missing — an
    empty result with no explanation is the thing this replaces.
    """
    offsets = PROBE_OFFSETS[:MAX_PROBES] if shiftable else (0,)
    attempts: List[Dict[str, str]] = []
    last = None

    for offset in offsets:
        candidate = _shift(window, offset) if offset else dict(window)
        # A shift can walk a window backwards past today; there is no point
        # spending an API call to be told nothing departs yesterday.
        if _in_the_past(candidate):
            continue

        attempts.append(candidate)
        probe = _probe(destination, origin, candidate, travellers)
        last = probe

        if _blocker(probe) is None:
            return {
                "destination": destination,
                "available": True,
                "window": candidate,
                "shifted_by": offset,
                "flights": probe["flights"],
                "hotels": probe["hotels"],
                "windows_tried": attempts,
                "blocked_by": None,
                **_priced(probe, travellers, allocation, budget_total),
            }

    # Nothing worked. Hand back the last probe anyway — showing "flights
    # exist, no rooms" beats showing nothing, and it's what tells the user
    # which constraint to relax.
    probe = last or {"window": window, "flights": [], "hotels": [],
                     "flight_error": None, "hotel_error": None}
    return {
        "destination": destination,
        "available": False,
        "window": probe["window"],
        "shifted_by": None,
        "flights": probe["flights"],
        "hotels": probe["hotels"],
        "windows_tried": attempts,
        "blocked_by": _blocker(probe) or "both",
        "flight_error": probe.get("flight_error"),
        "hotel_error": probe.get("hotel_error"),
        **_priced(probe, travellers, allocation, budget_total),
    }


def for_destinations(
    destinations: List[str],
    origin: str,
    windows: Dict[str, Dict[str, str]],
    travellers: int,
    allocation: Dict[str, float],
    budget_total: float,
    shiftable: bool,
) -> Dict[str, Dict[str, Any]]:
    """Reconcile every shortlisted destination, all at once.

    Destinations are independent — each gets its own window, since the
    right week for Shillong isn't the right week for Goa — so they run
    concurrently. `windows` supplies each one's starting point, which is
    the window Agent 0's research already picked for it.
    """
    shortlist = destinations[:MAX_DESTINATIONS]
    if not shortlist:
        return {}

    def one(destination: str) -> Dict[str, Any]:
        try:
            return for_destination(
                destination, origin, windows[destination], travellers,
                allocation, budget_total, shiftable,
            )
        except Exception as exc:                       # noqa: BLE001 - one bad destination
            logger.exception("Availability failed for %s", destination)
            return {
                "destination": destination, "available": False,
                "window": windows.get(destination), "flights": [], "hotels": [],
                "windows_tried": [], "blocked_by": "error", "error": str(exc),
                "nights": 0, "cheapest_flight": None, "cheapest_hotel_night": None,
                "hotel_total": None, "trip_total": None,
                "flights_fit": False, "hotel_fits": False, "fits_budget": False,
            }

    with ThreadPoolExecutor(max_workers=len(shortlist)) as pool:
        return {r["destination"]: r for r in pool.map(one, shortlist)}
