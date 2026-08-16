"""
Budget Allocator — shared service (PRD section 6), *not* a user-facing agent.

Splits the total trip budget across pipeline stages up front. Agent 1/2
draw down their slice as they book (see budget_remaining updates in those
agents); building real reallocation logic (moving unused flight budget into
hotel budget, etc. — PRD Phase 4) is future work, this just does the
initial split.

Two vocabularies meet here, deliberately:

  user-facing   travel / hotel / activities   — what Agent 0's intake asks
                                                about, three buckets someone
                                                can reason about
  internal      flights / hotel / itinerary   — what the agents actually
                / buffer                        draw against

`split_from_preference` is the translation between them. The buffer is
never offered to the user (nobody budgets for a buffer on purpose) — it's
held back off the top, and their percentages divide what's left.
"""
from typing import Any, Dict, Optional

DEFAULT_SPLIT = {
    "flights": 0.35,
    "hotel": 0.35,
    "itinerary": 0.20,
    "buffer": 0.10,
}

# The same default expressed in the three buckets the intake form shows,
# so the form's sliders open on the allocator's own recommendation. Whole
# percentages, not fractions — this one crosses the wire to the UI, and
# normalise_preference rescales either form anyway.
DEFAULT_PREFERENCE = {
    "travel": 35,
    "hotel": 35,
    "activities": 30,
}

BUCKETS = ("travel", "hotel", "activities")

# How lopsided the hotel-vs-activities shares have to be before we read
# intent into them, rather than calling it a balanced trip.
_STYLE_MARGIN = 0.10


def allocate(total_budget: float, split: Dict[str, float] = DEFAULT_SPLIT) -> Dict[str, float]:
    return {category: round(total_budget * pct, 2) for category, pct in split.items()}


def normalise_preference(pref: Optional[Dict[str, float]]) -> Dict[str, float]:
    """Clean up a user-supplied travel/hotel/activities split.

    Accepts whatever the form or the LLM parser produced — percentages
    (35) or fractions (0.35), a bucket missing, or three numbers that
    don't add up — and returns three fractions summing to 1.0. Rescaling
    rather than rejecting is the point: someone typing "half on hotels,
    a bit on activities" should not hit a validation error.
    """
    values = {b: _number(pref, b) for b in BUCKETS}
    total = sum(values.values())

    if total <= 0:
        values = {b: float(DEFAULT_PREFERENCE[b]) for b in BUCKETS}
        total = sum(values.values())

    return {b: round(v / total, 4) for b, v in values.items()}


def _number(pref: Optional[Dict[str, Any]], bucket: str) -> float:
    try:
        return max(0.0, float((pref or {}).get(bucket) or 0))
    except (TypeError, ValueError):
        return 0.0


def split_from_preference(pref: Optional[Dict[str, float]]) -> Dict[str, float]:
    """Turn the user's three-bucket preference into the four-way internal
    split. The buffer keeps its default share off the top; travel, hotel
    and activities divide the rest in the ratio the user asked for."""
    fractions = normalise_preference(pref)
    spendable = 1.0 - DEFAULT_SPLIT["buffer"]

    return {
        "flights": round(fractions["travel"] * spendable, 4),
        "hotel": round(fractions["hotel"] * spendable, 4),
        "itinerary": round(fractions["activities"] * spendable, 4),
        "buffer": DEFAULT_SPLIT["buffer"],
    }


def reallocate(
    allocation: Dict[str, float],
    total: float,
    needed_flights: Optional[float],
    needed_hotel: Optional[float],
) -> Optional[Dict[str, float]]:
    """Shift budget between slices to cover what things actually cost.

    The initial split is a heuristic guess made before anything was priced
    (PRD section 6). Once real fares are in, one slice routinely overshoots
    while another is left unspent — flights at 29k against a 21k slice,
    with the hotel coming in half its allowance. Asking the user to "raise
    their flight budget" in that situation is nonsense: the money is
    already there, in the wrong bucket.

    So this covers the real costs first and lets activities and the buffer
    absorb the difference. Returns None when the total genuinely doesn't
    stretch — that IS a real shortfall, and the user has to be asked.
    """
    flights = max(allocation["flights"], needed_flights or 0)
    hotel = max(allocation["hotel"], needed_hotel or 0)

    if flights + hotel > total:
        return None
    if flights == allocation["flights"] and hotel == allocation["hotel"]:
        return None                                    # nothing to move

    leftover = total - flights - hotel
    unpinned = allocation["itinerary"] + allocation["buffer"]
    rebalanced = {"flights": round(flights, 2), "hotel": round(hotel, 2)}
    for category in ("itinerary", "buffer"):
        ratio = (allocation[category] / unpinned) if unpinned else 0.5
        rebalanced[category] = round(leftover * ratio, 2)
    return rebalanced


def style_from_preference(pref: Optional[Dict[str, float]]) -> str:
    """Read trip intent off the budget split.

    Someone putting most of their money into the hotel is buying a place
    to be; someone putting it into activities is buying things to do. That
    distinction is worth more to Agent 0's research and Agent 3's
    itineraries than any question we could ask directly, and it comes free
    with a question we're already asking.
    """
    fractions = normalise_preference(pref)
    hotel, activities = fractions["hotel"], fractions["activities"]

    if activities - hotel >= _STYLE_MARGIN:
        return "activities"
    if hotel - activities >= _STYLE_MARGIN:
        return "relaxation"
    return "balanced"
