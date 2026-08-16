"""
Destination research for Agent 0 (PRD section 7).

`research_destinations` is the core of it: given a freeform description of
what someone wants ("north east India, want to see cherry blossoms"), it
produces concrete candidate destinations, each with a reason and the best
time to visit within their stated date constraint.

Two things worth knowing before editing:

1. The LLM suggests destinations; Google Places only *verifies* they exist.
   It is deliberately not the other way around — feeding a descriptive
   sentence into Places Text Search returns location-biased junk
   (attractions near the caller's own IP), because that endpoint expects a
   place-shaped query like "restaurants in Paris", not a description of an
   intent.

2. Windows come back as machine-usable ISO start/end dates, not just prose
   labels, because Agent 1/2 book against them.

There's no dedicated weather/climate API wired up (see PRD section 14), so
seasonality reasoning currently comes from the model's own knowledge —
swap in a real seasonality API if you want it grounded in measured data.

Note: this project's Google Maps key is restricted to the *legacy* Places
API. If you enable "Places API (New)" in Cloud Console, migrating is a
drop-in swap of `_looks_like_a_place`'s HTTP call only.
"""
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.services.llm import ask_groq, parse_llm_json

PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"


def look_up_place(name: str) -> Optional[Dict[str, Any]]:
    """Find a place on Google Places, returning the bits the UI shows.

    Doubles as the hallucination check — a name Places can't find returns
    None and gets dropped, so a made-up or misspelled destination never
    reaches flight search.

    Photo/rating come from this same call, so enriching a card costs no
    extra API request. `photo_ref` is deliberately not a URL: rendering it
    needs the Maps key, so the frontend fetches it through the backend's
    /photo proxy instead of ever seeing the key.
    """
    response = httpx.get(
        PLACES_TEXT_SEARCH_URL,
        params={"query": name, "key": settings.google_maps_api_key},
        timeout=10,
    )
    response.raise_for_status()
    results = response.json().get("results")
    if not results:
        return None

    top = results[0]
    photos = top.get("photos") or []
    place_id = top.get("place_id")
    return {
        "place_id": place_id,
        "address": top.get("formatted_address"),
        # Localities (cities) have no rating; POIs do. Both are possible here.
        "rating": top.get("rating"),
        "review_count": top.get("user_ratings_total"),
        "photo_ref": photos[0]["photo_reference"] if photos else None,
        "maps_url": (
            f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else None
        ),
    }


def _window_rules(trip_days: Optional[int], fixed_windows: List[Dict[str, str]]) -> str:
    """How much freedom the model has over each candidate's dates.

    Fixed dates leave none — the user has already committed, and a
    candidate proposing its own better week is just noise they can't act
    on. A flexible month leaves the choice open per candidate, which is
    the whole value of asking for one: the best week inside March differs
    by destination.
    """
    if fixed_windows:
        slots = "; ".join(f"{w['start']} to {w['end']}" for w in fixed_windows)
        return (
            f"- Their dates are FIXED: {slots}. Use exactly these dates for "
            "every suggestion — do not propose a different window. Instead, "
            'use "season_note" to say honestly what those dates are like at '
            "that place, including if it's a poor time to visit.\n"
        )

    return (
        "- Their dates are flexible. Within their stated constraint, pick "
        "the genuinely best window for each place — they may differ between "
        "suggestions, and that difference is useful to them.\n"
        "- Every window must start in the future.\n"
        + (
            f"- Make each window about {trip_days} days long.\n"
            if trip_days
            else "- If no trip length was given, make windows about 7 days.\n"
        )
    )


def research_destinations(
    destination_query: str,
    date_query: str,
    max_results: int = 6,
    context: str = "",
    trip_days: Optional[int] = None,
    fixed_windows: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Suggest candidate destinations plus the best window to visit each.

    `context` is the trip's criteria as a sentence (see
    intake.summarise) — who's going, from where, on what budget, and
    whether their money is going on the hotel or on things to do. It is
    what stops the model proposing Zermatt to a family of four on a
    domestic budget, and it's equally load-bearing on a mid-flow change of
    mind ("somewhere with snow"), where the query alone has dropped
    everything already agreed.

    `fixed_windows` pins the dates when the user named specific ones;
    otherwise each candidate gets the window that suits it best.

    Returns [{name, why, window, start, end}], verified to be real places.
    """
    today = date.today().isoformat()
    prompt = (
        "A traveller described the trip they want. Suggest up to "
        f"{max_results} real, specific destinations (cities or towns) that "
        "fit, and for each one the best time to go.\n\n"
        f"What they want: {destination_query!r}\n"
        f"Their date constraint: {date_query or 'no constraint given'}\n"
        + (f"About this trip and who's taking it: {context}\n" if context else "")
        + f"Today is {today}.\n\n"
        "Rules:\n"
        + (
            "- Everything above is already settled. Stay inside it: same "
            "country/region, reachable from where they're setting off, and "
            "realistically affordable on that budget for that many people. "
            "Only go outside it if the traveller explicitly asked to.\n"
            if context
            else ""
        )
        + "- Suggest actual named cities/towns someone would fly to and stay "
        "in, NOT individual attractions or landmarks.\n"
        "- If they named a region, every suggestion must be inside it.\n"
        "- If they mentioned a seasonal event or scenery, prefer places "
        "genuinely known for it, and time the window to match it.\n"
        "- If they already named one specific city, return just that one.\n"
        + _window_rules(trip_days, fixed_windows or [])
        + '\n"why" should be one specific sentence on why this place fits what '
        "they asked for — reference their actual situation (budget, who's "
        "going, where they're coming from) rather than describing the place "
        "in general.\n"
        '"season_note" should be one short sentence on why that window is '
        "the best time to go.\n\n"
        "Respond with ONLY JSON:\n"
        '{"destinations": [{"name": "<city>", "why": "<sentence>", '
        '"window": "<e.g. Oct 12-19>", "start": "YYYY-MM-DD", '
        '"end": "YYYY-MM-DD", "season_note": "<sentence>"}]}'
    )
    raw = ask_groq(prompt, json_mode=True, max_tokens=2048)
    suggested = parse_llm_json(raw).get("destinations", [])

    verified = []
    for d in suggested:
        if not d.get("name"):
            continue
        place = look_up_place(d["name"])
        if place:
            verified.append({**d, **place})

    if not verified:
        raise ValueError(f"No destinations found for: {destination_query!r}")
    return verified[:max_results]
