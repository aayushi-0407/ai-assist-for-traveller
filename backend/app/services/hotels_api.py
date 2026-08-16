"""
Hotel search via SerpApi's Google Hotels engine (PRD Agent 2).

No book() here on purpose — per PRD section 7, hotels are search +
deep-link only (Amadeus/Hotelbeds don't offer instant self-serve booking
access, see PRD section 12), so this module only finds options and hands
back the provider's own booking link for the user to finish on their site.
"""
from typing import Any, Dict, List
from urllib.parse import quote_plus

import httpx

from app.config import settings

SEARCH_URL = "https://serpapi.com/search.json"


def search(
    destination: str,
    date_window: Dict[str, str],
    travellers: int,
) -> List[Dict[str, Any]]:
    """Return every property found, unfiltered — budget filtering is the
    agent's job, so it can tell the user the cheapest actual price when
    nothing fits (see agent2_hotels.py)."""
    response = httpx.get(
        SEARCH_URL,
        params={
            "engine": "google_hotels",
            "q": f"{destination} hotels",
            "check_in_date": date_window["start"],
            "check_out_date": date_window["end"],
            "adults": travellers,
            # Ask SerpApi for rupees directly rather than converting after
            # the fact — no FX rounding, and it matches the user's budget.
            "currency": "INR",
            "api_key": settings.hotels_api_key,
        },
        timeout=15,
    )
    response.raise_for_status()
    properties = response.json().get("properties", [])

    # A property is only usable here if it has both a price and a booking
    # link — the link IS the booking mechanism for Agent 2 (search +
    # deep-link only, PRD section 7), so a property without one can't be
    # actioned. SerpApi returns `link: null` for some listings.
    options = [
        {
            "id": f"ht_{i}",
            "name": prop.get("name"),
            "price": prop["rate_per_night"]["extracted_lowest"],
            "currency": "INR",
            "rating": prop.get("overall_rating"),
            "booking_link": prop["link"],
            # Everything below is display-only, for comparing at a glance.
            # It all comes from the same search response, so surfacing it
            # costs no extra API request.
            "review_count": prop.get("reviews"),
            "hotel_class": prop.get("hotel_class"),
            "location_rating": prop.get("location_rating"),
            "amenities": (prop.get("amenities") or [])[:4],
            # Google's own CDN URLs — usable directly in <img>, no key
            # needed, unlike Places photos (which go via /photo).
            "image": (prop.get("images") or [{}])[0].get("thumbnail"),
            # Deliberately a Google Maps search rather than SerpApi's
            # `serpapi_google_hotels_reviews_link`: that one is an API
            # endpoint needing auth, so it just errors in a browser tab.
            # This opens the hotel's real listing with its reviews.
            "reviews_url": (
                "https://www.google.com/maps/search/?api=1&query="
                + quote_plus(f"{prop.get('name')} {destination}")
            ),
        }
        for i, prop in enumerate(properties)
        if prop.get("rate_per_night", {}).get("extracted_lowest") is not None
        and prop.get("link")
    ]

    return options
