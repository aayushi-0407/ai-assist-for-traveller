"""
The four planning criteria Agent 0 has to fill before it can research
anything worth showing:

  1. destination  — where they want to go. Already plural everywhere: the
                    research step returns candidates and the user
                    shortlists a set, so nothing extra is needed here
                    beyond the freeform `destination_query`.
  2. source       — where they set off FROM. Plural: a group can converge
                    on one place from several cities.
  3. window       — when they can travel. Either a fixed slot (or a few)
                    or a looser month/season to place the trip inside.
  4. budget       — the total, plus how they want it divided between
                    travel, hotel and activities.

This module is the pure-logic half of that: shape-normalising, working out
what's still missing, and deriving the fields the rest of the pipeline
reads. Anything needing an LLM lives in services/nlu.py, and the pause
itself lives in agents/agent0_best_time.py — keeping this file free of
both makes the criteria rules directly testable.

Why criteria come before research: party size, departure city and budget
all change which destinations are worth suggesting at all. Researching
first and asking after means proposing Ladakh to four people on a weekend
budget, then discarding the answer.
"""
from typing import Any, Dict, FrozenSet, List, Optional

from app.services import budget as budget_service

PARTY_TYPES = ("individual", "family", "group")

# --------------------------------------------------------------------------
# What Agent 0 must have before it hands off. Two tiers, because "keep
# asking until it's filled" is only safe for fields that can actually be
# answered — a field with no fallback and a user who won't answer it is a
# hung node, not a thorough one.
#
# REQUIRED  no fallback exists, so the intake loop never gives up on these.
#           An unknown budget makes every suggestion a guess; an unknown
#           origin makes "can they even get there" unanswerable; an unknown
#           destination brief leaves nothing to research.
#
# EXPECTED  Agent 0 still contracts to produce these, and the loop chases
#           them — but each has a defensible default, so after
#           MAX_STALLED_ROUNDS of getting nowhere it concedes, applies the
#           default and says which assumption it made. See `outstanding`.
# --------------------------------------------------------------------------
REQUIRED = ("destination_query", "origins", "budget_total")
EXPECTED = ("party_type", "date_query", "trip_days", "budget_split_pref")

# How many replies in a row may fail to fill anything new before the loop
# stops chasing the EXPECTED fields. Two gives the user a genuine second
# attempt — a mis-parse followed by a rephrase — without badgering.
MAX_STALLED_ROUNDS = 2

# Only used if the user actively declines to name a figure. Every amount
# in this system is INR (see services/fx.py — providers quoting anything
# else are converted before they reach the pipeline), so this is rupees:
# the old 2000 was a dollar-era default that reads as an impossible budget
# once everything else is in rupees.
FALLBACK_BUDGET = 50000.0
FALLBACK_TRIP_DAYS = 7

# The TripState keys `derive` guarantees once REQUIRED is satisfied.
# Checked on the way out as an invariant, not as something to ask about:
# a gap here is a bug in derive(), which no amount of re-asking can fix.
# `same_origin` is deliberately absent — False is a legitimate value and
# would read as unset here.
CONTRACT = (
    "destination_query", "party_type", "origins", "origin", "travellers",
    "date_mode", "trip_days", "budget_total", "budget_allocation",
    "budget_split_pref", "trip_style",
)

_FIELD_LABELS = {
    "destination_query": "some idea of where you'd like to go",
    "origins": "where you're travelling from",
    "budget_total": "your total budget",
    "party_type": "who's travelling",
    "date_query": "when you want to travel",
    "trip_days": "how many days you've got",
    "budget_split_pref": "how you'd like the budget divided",
}

# What the loop assumed for an EXPECTED field it gave up chasing. Past
# tense: these are only ever read back after the default has been applied.
# Keys must match EXPECTED.
_CONCESSIONS = {
    "party_type": "worked out the party from your head count",
    "date_query": "picked the season myself",
    "trip_days": f"planned for {FALLBACK_TRIP_DAYS} days",
    "budget_split_pref": "used a standard budget split",
}


def blank() -> Dict[str, Any]:
    """An empty criteria set — every field explicitly unknown."""
    return {
        "destination_query": None,
        "party_type": None,
        "same_origin": None,
        "origins": [],
        "travellers": None,
        "date_mode": None,
        "date_query": None,
        "trip_days": None,
        "budget_total": None,
        "budget_split_pref": None,
    }


def normalise_origins(
    raw: Any, total_travellers: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Coerce whatever came back into [{"city": str, "travellers": int}].

    Tolerant on input shape because three sources feed this: the intake
    form (already structured), the LLM parser (usually structured, not
    always), and the opening message (often just "from Delhi"). A bare
    string, a list of strings and a list of dicts all have to work.
    """
    if not raw:
        return []
    if isinstance(raw, (str, dict)):
        raw = [raw]

    cleaned: List[Dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, str):
            city, heads = entry.strip(), None
        elif isinstance(entry, dict):
            city = str(entry.get("city") or entry.get("origin") or "").strip()
            heads = entry.get("travellers") or entry.get("count")
        else:
            continue

        if not city:
            continue
        try:
            heads = max(1, int(heads)) if heads else None
        except (TypeError, ValueError):
            heads = None
        cleaned.append({"city": city, "travellers": heads})

    if not cleaned:
        return []

    # Fill in head counts. One origin means everyone leaves from there;
    # several with nothing stated means split the party evenly, with any
    # remainder landing on the first group so the total still adds up.
    unstated = [o for o in cleaned if o["travellers"] is None]
    if unstated:
        if len(cleaned) == 1:
            cleaned[0]["travellers"] = max(1, total_travellers or 1)
        else:
            known = sum(o["travellers"] or 0 for o in cleaned)
            spare = max(len(unstated), (total_travellers or len(cleaned)) - known)
            each, extra = divmod(spare, len(unstated))
            for i, origin in enumerate(unstated):
                origin["travellers"] = max(1, each + (extra if i == 0 else 0))

    return cleaned


def primary_origin(origins: List[Dict[str, Any]]) -> Optional[str]:
    """The city Agent 1 actually prices a route from.

    The biggest group wins, so the fare that does get checked covers the
    most travellers. The remaining origins stay in state, unpriced, until
    Agent 1 learns to fan out across them.
    """
    if not origins:
        return None
    return max(origins, key=lambda o: o.get("travellers") or 1)["city"]


def headcount(origins: List[Dict[str, Any]], fallback: int = 1) -> int:
    total = sum(o.get("travellers") or 0 for o in origins)
    return total or fallback


def infer_party_type(travellers: int) -> str:
    return "individual" if travellers <= 1 else "group"


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def sanitise(update: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Coerce a parsed reply into the shapes the rest of this module expects.

    Both sources of an update can be loose — an LLM asked for one of three
    enum values will occasionally return a fourth, and the form posts
    numbers as strings. Anything that can't be salvaged becomes None, which
    merge() then treats as "not mentioned" so the previous value survives
    rather than a bad one replacing it.
    """
    if not update:
        return {}

    party = update.get("party_type")
    mode = update.get("date_mode")
    travellers = _as_int(update.get("travellers"))
    trip_days = _as_int(update.get("trip_days"))
    budget = update.get("budget_total")
    try:
        budget = float(budget) if budget not in (None, "") else None
    except (TypeError, ValueError):
        budget = None

    return {
        "destination_query": update.get("destination_query"),
        "party_type": party if party in PARTY_TYPES else None,
        "origins": normalise_origins(update.get("origins"), travellers),
        "travellers": travellers if travellers and travellers > 0 else None,
        "date_mode": mode if mode in ("fixed", "flexible") else None,
        "date_query": update.get("date_query"),
        "trip_days": trip_days if trip_days and trip_days > 0 else None,
        "budget_total": budget if budget and budget > 0 else None,
        "budget_split_pref": update.get("budget_split_pref"),
        "same_origin": update.get("same_origin"),
    }


def merge(known: Dict[str, Any], update: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Layer a reply on top of what's already known.

    Only non-empty values overwrite: every parser returns null for things
    the user didn't mention, and a null must not erase a value the opening
    message already gave us. `same_origin` is special-cased because False
    is a real answer, not an absent one.
    """
    merged = {**known}
    for key, value in (update or {}).items():
        if key == "same_origin":
            if value is not None:
                merged[key] = bool(value)
        elif value not in (None, "", [], {}):
            merged[key] = value
    return merged


def missing(criteria: Dict[str, Any]) -> List[str]:
    """The REQUIRED fields still unanswered. The loop never exits on these."""
    return [field for field in REQUIRED if not criteria.get(field)]


def _expected_gaps(criteria: Dict[str, Any]) -> List[str]:
    gaps = []
    for field in EXPECTED:
        if criteria.get(field):
            continue
        # A fixed window already states its own length, so asking how many
        # days is asking something they've answered.
        if field == "trip_days" and criteria.get("date_mode") == "fixed":
            continue
        gaps.append(field)
    return gaps


def outstanding(criteria: Dict[str, Any], concede: bool = False) -> Dict[str, List[str]]:
    """Everything Agent 0 is still waiting on, split by whether it blocks.

    `concede=True` drops the EXPECTED tier — set by the node once the last
    few replies stopped filling anything in, so an unanswerable question
    can't hold the pipeline open indefinitely.
    """
    return {
        "required": missing(criteria),
        "expected": [] if concede else _expected_gaps(criteria),
    }


def complete(gaps: Dict[str, List[str]]) -> bool:
    return not gaps["required"] and not gaps["expected"]


def filled(criteria: Dict[str, Any]) -> FrozenSet[str]:
    """Which tracked fields currently hold a value.

    The loop compares this across rounds to tell a reply that moved things
    forward from one that didn't — progress, not reply count, is what
    decides whether asking again is worth anything.
    """
    return frozenset(f for f in REQUIRED + EXPECTED if criteria.get(f))


def describe(fields: List[str]) -> str:
    """Human phrasing for a re-ask, e.g. "your total budget"."""
    labels = [_FIELD_LABELS.get(f, f) for f in fields]
    if len(labels) <= 1:
        return "".join(labels)
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def describe_concessions(fields: List[str]) -> str:
    """What the loop assumed for the fields it stopped chasing."""
    notes = [_CONCESSIONS[f] for f in fields if f in _CONCESSIONS]
    if len(notes) <= 1:
        return "".join(notes)
    return f"{', '.join(notes[:-1])} and {notes[-1]}"


def validate(derived: Dict[str, Any]) -> List[str]:
    """Invariant check on the way out of the node: did derive() actually
    produce everything Agent 0 promises downstream?

    Distinct from `missing`, which is about the user. This is about us —
    anything it catches is a bug in derive(), so the node raises rather
    than asking the user to fix it for us.
    """
    return [f for f in CONTRACT if derived.get(f) in (None, "", [], {})]


def derive(criteria: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a filled criteria set into the TripState fields agents read.

    Everything here is a consequence of the four criteria rather than a
    fifth thing to ask about: the primary origin, the head count, the
    four-way budget allocation and the trip style are all computed, never
    collected.
    """
    origins = normalise_origins(criteria.get("origins"), criteria.get("travellers"))
    travellers = headcount(origins, criteria.get("travellers") or 1)

    total = float(criteria.get("budget_total") or FALLBACK_BUDGET)
    preference = budget_service.normalise_preference(criteria.get("budget_split_pref"))

    return {
        "destination_query": criteria.get("destination_query") or "",
        "party_type": criteria.get("party_type") or infer_party_type(travellers),
        # A single origin means one departure point by definition; with
        # several it's only "same" if the user said so, which they can't
        # coherently have.
        "same_origin": len(origins) <= 1,
        "origins": origins,
        "origin": primary_origin(origins),
        "travellers": travellers,
        "date_mode": criteria.get("date_mode") or "flexible",
        "date_query": criteria.get("date_query") or "",
        "budget_total": total,
        "budget_remaining": total,
        "budget_split_pref": preference,
        "budget_allocation": budget_service.allocate(
            total, budget_service.split_from_preference(preference)
        ),
        "trip_style": budget_service.style_from_preference(preference),
    }


_STYLE_BRIEF = {
    "relaxation": (
        "They're weighting their budget towards where they stay, so favour "
        "places worth slowing down in over places with a long sightseeing list."
    ),
    "activities": (
        "They're weighting their budget towards things to do, so favour places "
        "with plenty going on over quiet retreats."
    ),
    "balanced": "",
}


def summarise(state: Dict[str, Any]) -> str:
    """The criteria as a sentence, for the research prompt.

    Research reads this instead of the raw state so that adding a
    criterion is a change in one place rather than in every prompt that
    ought to respect it.
    """
    bits: List[str] = []

    origins = state.get("origins") or []
    if len(origins) == 1:
        bits.append(f"departing from {origins[0]['city']}")
    elif origins:
        joined = ", ".join(f"{o['travellers']} from {o['city']}" for o in origins)
        bits.append(f"departing separately ({joined}), so they need a common meeting point")

    travellers = state.get("travellers") or 1
    party = state.get("party_type") or infer_party_type(travellers)
    bits.append(
        f"{travellers} traveller(s)" if party == "individual"
        else f"a {party} of {travellers}"
    )

    if state.get("budget_total"):
        bits.append(f"total budget {state['budget_total']:,.0f}")

    allocation = state.get("budget_allocation") or {}
    if allocation.get("itinerary"):
        bits.append(
            f"of which about {allocation['itinerary']:,.0f} is for activities and food"
        )

    if state.get("date_mode") == "fixed" and state.get("date_windows"):
        slots = ", ".join(f"{w['start']} to {w['end']}" for w in state["date_windows"])
        bits.append(f"fixed travel dates: {slots}")

    summary = "; ".join(bits)
    style_note = _STYLE_BRIEF.get(state.get("trip_style") or "balanced", "")
    return f"{summary}. {style_note}".strip() if style_note else summary
