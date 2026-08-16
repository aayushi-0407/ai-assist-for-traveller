"""
Natural-language understanding helpers — turns the user's free-text chat
messages into the structured values the agents need.

This is what makes the ChatGPT-style interface work: the frontend sends
whatever the user typed, and each pipeline stage calls the matching parser
here to interpret that text *in the context of what was just asked*.

Every parser also accepts an explicit `selection` from the UI (the user
clicking a card instead of typing). When a selection is present it wins —
no LLM call needed, and no chance of misreading a click.
"""
from datetime import date
from typing import Any, Dict, List, Optional

from app.services.llm import ask_groq, parse_llm_json


def parse_opening_message(message: str) -> Dict[str, Any]:
    """Pull the four planning criteria out of the user's very first message.

    Prefills Agent 0's intake form (see services/intake.py) so the user is
    confirming what they already said rather than retyping it. Missing
    values come back as null rather than guesses — callers decide the
    fallback, since e.g. an absent budget should mean "no cap", not "0".
    """
    prompt = (
        "Extract trip-planning details from this message. Return JSON.\n\n"
        f"Message: {message!r}\n\n"
        "Fields:\n"
        '- "destination_query": everything they said about WHERE they want to '
        "go, including vague descriptions, regions, scenery, or events. Keep "
        "their own wording. null if they said nothing about where.\n"
        '- "date_query": everything they said about WHEN or for how long. '
        "null if nothing.\n"
        '- "date_mode": "fixed" if they named specific dates or a specific '
        'week, "flexible" if they only gave a month, season or rough period, '
        "null if they said nothing about when.\n"
        '- "trip_days": how many days the trip should last, null if not stated.\n'
        '- "budget_total": total trip budget as a number, null if not stated.\n'
        '- "travellers": total number of people, null if not stated.\n'
        '- "party_type": "individual", "family" or "group" if it is clear from '
        "how they describe who is going, null otherwise.\n"
        '- "origins": the cities they are travelling FROM, as a list of '
        '{"city": <name>, "travellers": <number or null>}. Usually one entry. '
        "Use several only if they clearly said different people are setting "
        "off from different places. Empty list if they did not say.\n\n"
        'Respond with ONLY JSON: {"destination_query": ..., "date_query": ..., '
        '"date_mode": ..., "trip_days": ..., "budget_total": ..., '
        '"travellers": ..., "party_type": ..., "origins": [...]}'
    )
    return parse_llm_json(ask_groq(prompt, json_mode=True))


def parse_intake_reply(
    message: str,
    known: Dict[str, Any],
    selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Read Agent 0's intake answer off a typed reply.

    The form (a `selection`) is the normal path and is trusted verbatim.
    This handles the person who answers the whole thing in prose instead —
    "three of us, two from Delhi one from Pune, first week of March, 90k,
    mostly on things to do".

    Only what they actually mentioned comes back; nulls leave the
    already-known value alone (see intake.merge).
    """
    if selection:
        return {
            "destination_query": selection.get("destination_query"),
            "party_type": selection.get("party_type"),
            "origins": selection.get("origins"),
            "travellers": selection.get("travellers"),
            "date_mode": selection.get("date_mode"),
            "date_query": selection.get("date_query"),
            "trip_days": selection.get("trip_days"),
            "budget_total": selection.get("budget_total"),
            "budget_split_pref": selection.get("budget_split_pref"),
        }

    prompt = (
        "A travel assistant asked a traveller to confirm the details of "
        "their trip. Extract whatever their reply provides.\n\n"
        f"Already known (do not repeat unless they changed it): {known}\n"
        f"They replied: {message!r}\n\n"
        "Fields — use null for anything they did not mention:\n"
        '- "destination_query": anything they said about WHERE they want to '
        "go, in their own words, including vague descriptions.\n"
        '- "party_type": "individual", "family" or "group".\n'
        '- "travellers": total number of people.\n'
        '- "origins": list of {"city": <name>, "travellers": <number or null>} '
        "for the places people are setting off from. Several entries only if "
        "different people leave from different cities.\n"
        '- "date_mode": "fixed" if they named specific dates, "flexible" if '
        "they gave a month or season to fit the trip into.\n"
        '- "date_query": what they said about when, in their own words.\n'
        '- "trip_days": how many days the trip should last.\n'
        '- "budget_total": total budget as a number.\n'
        '- "budget_split_pref": how they want the budget divided, as '
        '{"travel": <n>, "hotel": <n>, "activities": <n>} percentages adding '
        "up to 100. Infer it from intent as well as numbers — 'mostly "
        "sightseeing' means a high activities share, 'somewhere nice to relax' "
        "a high hotel share. null if they gave no signal either way.\n\n"
        "Respond with ONLY JSON with exactly those keys."
    )
    return parse_llm_json(ask_groq(prompt, json_mode=True))


def parse_destination_choice(
    message: str,
    candidates: List[Dict[str, Any]],
    selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Work out which candidate destination(s) the user wants itineraries
    for, and any date/length info they gave alongside."""
    if selection and selection.get("destinations"):
        return {
            "destinations": selection["destinations"],
            "date_query": selection.get("date_query"),
        }

    names = [c["name"] for c in candidates]
    prompt = (
        "The user was shown these candidate travel destinations:\n"
        f"{', '.join(names)}\n\n"
        f"They replied: {message!r}\n\n"
        "Which destinations do they want to see itineraries for? They may "
        "name one, several, or ask for all of them. Match loosely — a "
        "partial or misspelled name should map to the closest candidate. If "
        "they clearly mean all of them, return all. If you genuinely cannot "
        "tell, return an empty list.\n"
        "Also extract any dates or trip length they mention.\n\n"
        'Respond with ONLY JSON: {"destinations": ["<exact candidate name>", ...], '
        '"date_query": "<what they said about dates, or null>"}'
    )
    result = parse_llm_json(ask_groq(prompt, json_mode=True))
    # Guard against the model inventing a name that wasn't offered.
    result["destinations"] = [d for d in result.get("destinations", []) if d in names]
    return result


def parse_itinerary_choice(
    message: str,
    destinations: List[str],
    selection: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Which destination did the user settle on after comparing itineraries?"""
    if selection and selection.get("destination"):
        return selection["destination"]

    if len(destinations) == 1:
        # Nothing to disambiguate — treat any reply as confirmation.
        return destinations[0]

    prompt = (
        "The user compared trip itineraries for these destinations:\n"
        f"{', '.join(destinations)}\n\n"
        f"They replied: {message!r}\n\n"
        "Which single destination did they choose? Match loosely, including "
        'ordinal references like "the first one" or "the second option". '
        "Return null if you cannot tell.\n\n"
        'Respond with ONLY JSON: {"destination": "<exact name>" or null}'
    )
    chosen = parse_llm_json(ask_groq(prompt, json_mode=True)).get("destination")
    return chosen if chosen in destinations else None


def parse_origin(message: str, selection: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Extract the city the user is flying from."""
    if selection and selection.get("origin"):
        return selection["origin"]

    prompt = (
        f"The user was asked which city they are flying from. They said: {message!r}\n\n"
        "Extract just the city or airport name. Return null if they did not "
        "name a place.\n\n"
        'Respond with ONLY JSON: {"origin": "<city>" or null}'
    )
    return parse_llm_json(ask_groq(prompt, json_mode=True)).get("origin")


def parse_option_choice(
    message: str,
    options: List[Dict[str, Any]],
    label_field: str,
    selection: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Which flight/hotel did the user pick? Returns the option's id.

    Handles both direct references ("the Marriott") and comparative ones
    ("the cheapest", "the fastest", "the first one").
    """
    if selection and selection.get("option_id"):
        return selection["option_id"]

    # Every comparable attribute has to appear here — the model can only
    # resolve "the highest rated" / "the fastest" against fields it can
    # actually see in this listing.
    comparable = ("price", "currency", "rating", "duration_min", "stops")
    listing = "\n".join(
        f"{i + 1}. id={o['id']} | {o.get(label_field)} | "
        + " | ".join(f"{f}={o[f]}" for f in comparable if o.get(f) is not None)
        for i, o in enumerate(options)
    )
    prompt = (
        f"The user was shown these options:\n{listing}\n\n"
        f"They replied: {message!r}\n\n"
        "Which option did they choose? Understand comparative phrasing like "
        '"the cheapest", "the fastest", "the highest rated", and ordinals '
        'like "the second one". Return the exact id. Return null if unclear.\n\n'
        'Respond with ONLY JSON: {"option_id": "<id>" or null}'
    )
    chosen = parse_llm_json(ask_groq(prompt, json_mode=True)).get("option_id")
    return chosen if any(o["id"] == chosen for o in options) else None


def parse_budget_split(
    message: str,
    current: Dict[str, float],
    selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Optional[float]]:
    """Read an optional per-category budget override off a chat reply.

    Returns {"flights": n|None, "hotel": n|None} — None meaning "leave the
    automatic split alone". Unlike the other parsers this never re-asks on
    a miss: the question is optional, so anything that isn't clearly an
    amount ("looks good", "whatever you think") correctly means keep.
    """
    if selection:
        return {
            "flights": selection.get("flights"),
            "hotel": selection.get("hotel"),
        }

    prompt = (
        "A traveller was shown this automatic budget split and asked "
        "whether they'd like to change it:\n"
        f"flights={current['flights']}, hotel={current['hotel']}\n\n"
        f"They replied: {message!r}\n\n"
        "Extract any specific amount they want to spend on flights and on "
        "the hotel. Use null for a category they didn't give a number for. "
        "If they're happy with the split, declining to change it, or vague "
        "(e.g. 'looks good', 'you decide'), both must be null.\n\n"
        'Respond with ONLY JSON: {"flights": <number or null>, "hotel": <number or null>}'
    )
    result = parse_llm_json(ask_groq(prompt, json_mode=True))
    return {"flights": result.get("flights"), "hotel": result.get("hotel")}


def parse_date_window(date_query: str, trip_days_hint: Optional[int] = None) -> Dict[str, Any]:
    """Turn freeform date text into a concrete ISO start/end window."""
    today = date.today().isoformat()
    prompt = (
        f"Today is {today}. Convert this travel date description into a "
        f"concrete future date window: {date_query!r}\n\n"
        + (f"The trip should be about {trip_days_hint} days long.\n" if trip_days_hint else "")
        + "If only months are named, pick a sensible window inside them. If "
        "no length is given, assume 7 days. The window must start in the future.\n\n"
        'Respond with ONLY JSON: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}'
    )
    return parse_llm_json(ask_groq(prompt, json_mode=True))


def parse_date_windows(
    date_query: str, trip_days_hint: Optional[int] = None
) -> List[Dict[str, str]]:
    """Resolve fixed travel dates into one or more concrete ISO windows.

    Only used when the user said their dates are *fixed* — a flexible
    "sometime in March" is deliberately left unresolved at intake, because
    the best week inside March differs per destination and that's Agent 0's
    research job, not a decision to pin down before it runs.

    Returns a list because "the first week of March, or the last week if
    that's cheaper" is two real options, and the user shouldn't have to
    pick one before seeing anything.
    """
    today = date.today().isoformat()
    prompt = (
        f"Today is {today}. A traveller gave these fixed travel dates: "
        f"{date_query!r}\n\n"
        + (f"The trip should be about {trip_days_hint} days long.\n" if trip_days_hint else "")
        + "Convert them into concrete date windows. Return one window per "
        "distinct slot they offered — usually one, but more if they named "
        "alternatives. Every window must start in the future. If no length "
        "is given, assume 7 days.\n\n"
        'Respond with ONLY JSON: {"windows": [{"start": "YYYY-MM-DD", '
        '"end": "YYYY-MM-DD", "label": "<e.g. Mar 3-10>"}]}'
    )
    windows = parse_llm_json(ask_groq(prompt, json_mode=True)).get("windows") or []
    return [w for w in windows if w.get("start") and w.get("end")]
