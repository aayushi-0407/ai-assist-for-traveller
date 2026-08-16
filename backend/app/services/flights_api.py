"""
Flight search + booking via Duffel (PRD Agent 1), in test mode
(DUFFEL_API_KEY starting with `duffel_test_` — no real money moves).

Two Duffel quirks worth knowing before you touch this file:

1. Duffel needs IATA airport codes, not free-text place names. `_resolve_iata()`
   uses Duffel's own /places/suggestions endpoint to turn "Manali" into
   "KUU" (Kullu Manali Airport) before searching. This runs on every
   search() call — cheap and fine to re-run, unlike the offer search
   itself (see point 2).

2. search() is a REAL, NON-DETERMINISTIC call — each call to
   /air/offer_requests returns fresh offers with new offer IDs and
   slightly different prices, even for the same query. This is why
   agents/agent1_flights.py is split into a `search` node and a separate
   `approve_and_book` node rather than one node with search-then-interrupt:
   LangGraph replays a node's code from the top on every resume, so if
   search() lived before the interrupt() call, resuming would silently
   re-search and invalidate the offer ID the user actually picked. Keep
   that split — don't collapse it back into one function.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.services import fx
from app.services.llm import ask_groq, parse_llm_json

BASE_URL = "https://api.duffel.com"
HEADERS = {
    "Authorization": f"Bearer {settings.duffel_api_key}",
    "Duffel-Version": "v2",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _suggest_places(query: str) -> List[Dict[str, Any]]:
    response = httpx.get(
        f"{BASE_URL}/places/suggestions",
        headers=HEADERS,
        params={"query": query},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["data"]


def _plausible_match(place_query: str, candidate: Dict[str, Any]) -> bool:
    """Guard against Duffel's fuzzy search returning an unrelated airport.

    Its matching is substring-based and happily answers "Tawang" with
    "Awang Airport" in the Philippines. Requiring the query to actually
    appear in the airport's own name or city rejects that, while still
    accepting "Shillong"->Shillong Airport and "Delhi"->New Delhi.
    """
    query = place_query.strip().lower()
    haystacks = [
        (candidate.get("name") or "").lower(),
        (candidate.get("city_name") or "").lower(),
    ]
    return any(query in h for h in haystacks if h)


def _resolve_iata(place_query: str) -> Dict[str, str]:
    """Map a place name to a bookable airport.

    Returns {"iata", "airport", "city"} — the airport's own details, not
    the query's, because they often differ and the user needs to be told
    which one they're actually flying into.

    Plenty of real destinations have no airport of their own: Tawang is
    reached via Guwahati, Hawaii Kai is a Honolulu neighbourhood. A direct
    Duffel lookup returns nothing for those, so rather than dead-ending the
    trip we ask the LLM for the nearest commercial airport and verify that
    answer against Duffel before using it.
    """
    for candidate in _suggest_places(place_query):
        if _plausible_match(place_query, candidate):
            return {
                "iata": candidate["iata_code"],
                "airport": candidate.get("name") or candidate["iata_code"],
                "city": candidate.get("city_name") or place_query,
            }

    # Ask for the airport's CITY plus its COUNTRY, and verify both against
    # Duffel. Deliberately not asking for an IATA code: the model
    # hallucinates those (it offered "GUW" for Tawang, which is really
    # Atyrau in Kazakhstan; Guwahati is GAU). A city name can be checked
    # against Duffel's own city field, and the country check is what
    # actually stops a wrong-continent match from slipping through.
    prompt = (
        f"Which commercial airport do travellers normally use to reach "
        f"{place_query!r}? It is often in a different city.\n\n"
        'Respond with ONLY JSON: {"city": "<city the airport is in>", '
        '"country_code": "<2-letter ISO country code>"}'
    )
    guess = parse_llm_json(ask_groq(prompt, json_mode=True))
    city = (guess.get("city") or "").strip()
    country = (guess.get("country_code") or "").strip().upper()

    if city:
        for candidate in _suggest_places(city):
            same_country = (candidate.get("iata_country_code") or "").upper() == country
            if same_country and _plausible_match(city, candidate):
                return {
                    "iata": candidate["iata_code"],
                    "airport": candidate.get("name") or candidate["iata_code"],
                    "city": candidate.get("city_name") or city,
                }

    raise ValueError(
        f"Couldn't find an airport serving {place_query!r}. Try naming a "
        "nearby larger city."
    )


def _request_offers(slices: List[Dict[str, str]], travellers: int) -> List[Dict[str, Any]]:
    body = {
        "data": {
            "slices": slices,
            "passengers": [{"type": "adult"} for _ in range(max(1, travellers))],
            "cabin_class": "economy",
        }
    }
    response = httpx.post(
        f"{BASE_URL}/air/offer_requests",
        headers=HEADERS,
        params={"return_offers": "true", "limit": 5},
        json=body,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"]["offers"]


def search(
    origin: str,
    destination: str,
    date_window: Dict[str, str],
    travellers: int = 1,
    round_trip: bool = True,
) -> List[Dict[str, Any]]:
    """Return every offer found, unfiltered.

    Budget filtering is the agent's job, not this function's — when
    nothing fits, the agent needs the full list to tell the user what the
    cheapest option actually costs so they can decide whether to raise
    their budget.

    ROUND TRIP: two slices by default — out on `start`, back on `end` — so
    the flight has a return date the hotel checkout can actually be
    reconciled against (see services/availability.py). Duffel test
    inventory is patchy on regional routes, so a round-trip search that
    finds nothing retries one-way rather than reporting the destination
    unreachable; those options carry `has_return: False` and the UI says
    the return leg is unpriced.

    `travellers` becomes one adult passenger each, so `price` is the whole
    party's fare — comparing a single seat against a party budget would
    make every trip look affordable.
    """
    origin_place = _resolve_iata(origin)
    destination_place = _resolve_iata(destination)

    outbound = {
        "origin": origin_place["iata"],
        "destination": destination_place["iata"],
        "departure_date": date_window["start"],
    }
    inbound = {
        "origin": destination_place["iata"],
        "destination": origin_place["iata"],
        "departure_date": date_window["end"],
    }

    has_return = bool(round_trip and date_window.get("end"))
    offers = _request_offers([outbound, inbound] if has_return else [outbound], travellers)

    if not offers and has_return:
        has_return = False
        offers = _request_offers([outbound], travellers)

    # _to_option returns None for an offer priced in a currency we can't
    # turn into rupees — dropped here so nothing downstream ever sees a
    # non-INR price.
    options = [
        o for o in (_to_option(offer, date_window, has_return) for offer in offers)
        if o is not None
    ]
    # Carry the resolved airports onto every option so the UI can tell the
    # user *which* airport they're flying into — it may not be the place
    # they named (Tawang -> Guwahati), and silently booking a different
    # city would be a nasty surprise.
    for o in options:
        o["origin_airport"] = origin_place["airport"]
        o["destination_airport"] = destination_place["airport"]
        o["destination_city"] = destination_place["city"]

    return options


def _to_option(
    offer: Dict[str, Any], date_window: Dict[str, str], has_return: bool = False
) -> Optional[Dict[str, Any]]:
    """Flatten a Duffel offer into the shape the UI sorts and renders.

    Returns None if the fare can't be expressed in rupees — see the
    conversion block below.

    `duration_min` and `stops` describe the OUTBOUND slice only — they
    exist so the frontend can offer "cheapest / fastest / fewest stops"
    sorting, and mixing the return leg into those numbers would make the
    ranking meaningless. The return leg's own times ride alongside.
    """
    slices = offer["slices"]
    segments = slices[0]["segments"]
    departing_at = segments[0]["departing_at"]
    arriving_at = segments[-1]["arriving_at"]

    # A round-trip offer carries the return as a second slice. Reading it
    # off the offer rather than trusting date_window matters: the airline
    # may put the return on a different date than the one requested.
    return_leg: Dict[str, Any] = {"has_return": has_return and len(slices) > 1}
    if return_leg["has_return"]:
        back = slices[1]["segments"]
        return_leg.update({
            "return_departing_at": back[0]["departing_at"],
            "return_arriving_at": back[-1]["arriving_at"],
            "return_stops": len(back) - 1,
        })

    # Duffel quotes in the airline's own currency (EUR/USD in test mode),
    # but everything else in the app — the budget, hotel rates, every total
    # — is INR. `price` is therefore ALWAYS rupees: an offer that can't be
    # converted is dropped by the caller rather than emitted in a foreign
    # currency, because the moment a EUR figure reaches `affordable()` or
    # `budget_remaining` it is being compared against rupees.
    quoted = float(offer["total_amount"])
    quoted_currency = offer["total_currency"]
    in_inr, approximate = fx.to_inr(quoted, quoted_currency)
    if in_inr is None:
        return None

    return {
        "id": offer["id"],
        "carrier": segments[0]["operating_carrier"]["name"],
        "price": in_inr,
        "currency": fx.TARGET,
        # Kept for transparency: what the airline actually charges, and
        # whether the rupee figure came from a live rate or a fallback.
        "quoted_price": quoted,
        "quoted_currency": quoted_currency,
        "fx_approximate": approximate,
        "depart": date_window,
        "departing_at": departing_at,
        "arriving_at": arriving_at,
        "duration_min": _duration_minutes(departing_at, arriving_at),
        # One segment is a direct flight, so stops is segments - 1.
        "stops": len(segments) - 1,
        "origin": segments[0]["origin"]["iata_code"],
        "destination": segments[-1]["destination"]["iata_code"],
        **return_leg,
        # Needed to build the order in book() below — not shown to the
        # user, just carried through the option dict.
        "_passenger_id": offer["passengers"][0]["id"],
        "_requires_instant_payment": offer["payment_requirements"]["requires_instant_payment"],
    }


def _duration_minutes(departing_at: str, arriving_at: str) -> int:
    # Duffel timestamps are local to each airport and carry no timezone, so
    # this is wall-clock duration — close enough for ranking flights, but
    # don't treat it as exact across timezones.
    depart = datetime.fromisoformat(departing_at)
    arrive = datetime.fromisoformat(arriving_at)
    return max(0, int((arrive - depart).total_seconds() // 60))


# TODO: this is placeholder passenger data. A real product must collect
# actual traveller details (name, DOB, email, phone) before booking — Duffel
# requires them to issue a ticket. Wire this up to a real form once the
# rest of the flow is working; until then, every booking uses this same
# demo passenger.
_PLACEHOLDER_PASSENGER = {
    "title": "mr",
    "gender": "m",
    "given_name": "Traveller",
    "family_name": "Demo",
    "born_on": "1990-01-01",
    "email": "traveller@example.com",
    "phone_number": "+911234567890",
}


def book(option: Dict[str, Any]) -> Dict[str, Any]:
    if option["_requires_instant_payment"]:
        # This demo doesn't collect real payment — only book offers that
        # allow "hold" (pay later). Duffel test mode returns a realistic
        # mix of both, so most searches will have holdable options.
        raise ValueError(
            "Selected offer requires instant payment, which this boilerplate doesn't "
            "implement yet — pick a different option or add payment handling."
        )

    body = {
        "data": {
            "type": "hold",
            "selected_offers": [option["id"]],
            "passengers": [{"id": option["_passenger_id"], **_PLACEHOLDER_PASSENGER}],
        }
    }
    response = httpx.post(f"{BASE_URL}/air/orders", headers=HEADERS, json=body, timeout=30)
    response.raise_for_status()
    order = response.json()["data"]

    # Carry the whole option through (route, times, duration, stops) so the
    # summary UI can show the same detail the user picked from — listing
    # fields individually here silently drops any field added to _to_option
    # later. Internal "_"-prefixed plumbing is stripped on the way out.
    return {
        **{k: v for k, v in option.items() if not k.startswith("_")},
        "confirmation": order["booking_reference"],
    }
