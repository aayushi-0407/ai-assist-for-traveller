"""
TripState — the single shared object that flows through the whole pipeline
(PRD section 8: "holds the shared trip state").

Every agent node receives the current TripState and returns a dict of the
fields it added/changed; LangGraph merges that dict back into the state
before calling the next node. This is why each agent below only returns
the keys it's responsible for, not the whole state.

`total=False` means every field is optional — a field simply doesn't exist
yet until the agent responsible for it has run.

Pipeline order (see orchestrator.py):
    Agent 0 intake    (fill the four planning criteria)
 -> Agent 0 research  (candidate places + when to go)
 -> Agent 0 choose    (user shortlists)
 -> Agent 3 (itinerary per candidate, user compares and locks destination)
 -> Agent 4 (route optimisation for the winning itinerary)
 -> Agent 1 (flights)
 -> Agent 2 (hotels)
"""
from typing import Any, Dict, List, Optional, TypedDict


class TripState(TypedDict, total=False):
    # --- raw input: the user's first free-text message, plus whatever an
    # LLM managed to extract from it (see services/nlu.py) ---
    opening_message: str
    destination_query: str          # freeform, e.g. "a hill station", "NE India, cherry blossoms"
    date_query: str                 # freeform, e.g. "anytime July-Dec", "1 week in Oct"
    budget_total: float
    travellers: int
    calendar_connected: bool

    # ----------------------------------------------------------------
    # Agent 0 intake — the four planning criteria (see services/intake.py).
    #
    # The working draft, produced by the extract node and handed to the
    # intake pause. Unlike the flattened fields below it keeps unknowns as
    # explicit nulls, which is how the form knows what to still ask for.
    intake_criteria: Dict[str, Any]
    # EXPECTED fields the intake loop gave up chasing and defaulted, so the
    # next question can state the assumption rather than bury it.
    intake_assumptions: List[str]
    #
    # Everything below is captured BEFORE research runs, because party
    # size, origin and budget all change which destinations are worth
    # suggesting at all.
    # ----------------------------------------------------------------

    # Criterion 2 — source. Multiple people can set off from different
    # cities, so origins is the authoritative field and `origin` (below,
    # under Agent 1) is just the primary one derived from it.
    party_type: str                       # "individual" | "family" | "group"
    same_origin: bool                     # False => everyone departs separately
    origins: List[Dict[str, Any]]         # [{"city": str, "travellers": int}]

    # Criterion 3 — travel window. "fixed" means the user named specific
    # dates; "flexible" means they gave a month/season to place the trip
    # inside. Either way `date_windows` holds one or more concrete ISO
    # candidates, and selected_date_window (below) is the one in play.
    date_mode: str                        # "fixed" | "flexible"
    date_windows: List[Dict[str, str]]    # [{"start", "end", "label"}]

    # Criterion 4 — budget granularity. The share of the total the user
    # wants going to each bucket, as fractions summing to 1.0. Drives
    # budget_allocation instead of the default heuristic split, and
    # trip_style is read off it (heavy activities share => an active trip,
    # heavy hotel share => a relaxation trip).
    budget_split_pref: Dict[str, float]   # {"travel": .., "hotel": .., "activities": ..}
    trip_style: str                       # "relaxation" | "activities" | "balanced"

    # --- Budget Allocator (PRD section 6) ---
    budget_allocation: Dict[str, float]   # {"flights": x, "hotel": y, "itinerary": z, "buffer": w}
    budget_remaining: float

    # Set when the user changes their mind mid-flow about where they want
    # to go ("actually, somewhere with snow"). Conditional edges route back
    # to Agent 0, which researches this instead and then clears it.
    restart_query: Optional[str]

    # --- Agent 0: research candidate destinations + when to go ---
    # Each candidate: {name, why, window, start, end}
    candidate_destinations: List[Dict[str, Any]]
    # Which candidates the user wants itineraries for (1..n names).
    shortlisted_destinations: List[str]
    selected_date_window: Dict[str, str]    # {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
    trip_days: int

    # --- Agents 1+2, run jointly and in parallel with Agent 3 ---
    # Per shortlisted destination: the window where flights AND hotels both
    # have inventory, the options found there, and what it all costs.
    # Written by agents/availability.py; see services/availability.py for
    # why the two searches can't be independent.
    # {name: {available, window, shifted_by, blocked_by, flights, hotels,
    #         nights, cheapest_flight, hotel_total, trip_total, fits_budget}}
    availability: Dict[str, Dict[str, Any]]

    # --- Agent 3: one itinerary per shortlisted destination, then the pick ---
    # {destination_name: [{day, places, est_cost}, ...]}
    itinerary_options: Dict[str, List[Dict[str, Any]]]
    resolved_destination: str        # locked in only after the user compares
    itinerary: List[Dict[str, Any]]  # the winning destination's day plans

    # --- Agent 4: route optimisation ---
    routed_itinerary: List[Dict[str, Any]]

    # --- Agent 1: Flight Search & Booking ---
    # Primary departure city, derived from `origins` at intake (the group
    # with the most travellers wins). Agent 1 prices this one route; the
    # other entries in `origins` are captured but not yet searched.
    origin: Optional[str]
    flight_options: List[Dict[str, Any]]
    booked_flight: Dict[str, Any]

    # --- Agent 2: Hotel Search & Deep-Link Booking ---
    # No `booked_hotel` — Agent 2 doesn't complete a real booking (PRD
    # section 7); it hands back a chosen option plus a link to finish
    # booking on the provider's site.
    hotel_options: List[Dict[str, Any]]
    selected_hotel: Dict[str, Any]
