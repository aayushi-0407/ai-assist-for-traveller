"""
Route optimization (PRD Agent 4) using the real Google Distance Matrix API.

For a day's list of places, this fetches real pairwise travel times, then
picks the visiting order that minimizes total travel time. Per PRD section
12 ("exact TSP vs. heuristic"): a day realistically has a handful of stops
(~5), so brute-force over all orderings is cheap and exact; nearest-neighbor
is used as a fallback once the list gets large enough that brute force
would be too slow.
"""
from itertools import permutations
from typing import Any, Dict, List, Tuple

import httpx

from app.config import settings

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

# 8! = 40,320 orderings — fine to brute-force. Beyond that, fall back to
# nearest-neighbor rather than let this blow up combinatorially.
EXACT_SOLVE_LIMIT = 8


def _fetch_duration_matrix(places: List[str]) -> List[List[int]]:
    """Returns a durations[i][j] matrix in minutes, travel time from
    places[i] to places[j], via one Distance Matrix API call."""
    joined = "|".join(places)
    response = httpx.get(
        DISTANCE_MATRIX_URL,
        params={"origins": joined, "destinations": joined, "key": settings.google_maps_api_key},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "OK":
        raise ValueError(f"Distance Matrix error: {data.get('status')} {data.get('error_message', '')}")

    matrix = []
    for row in data["rows"]:
        durations = []
        for element in row["elements"]:
            if element.get("status") != "OK":
                # No route found between this pair (e.g. different
                # continents) — treat as very costly rather than fail the
                # whole day's route.
                durations.append(10**6)
            else:
                durations.append(element["duration"]["value"] // 60)
        matrix.append(durations)
    return matrix


def _best_order(matrix: List[List[int]]) -> List[int]:
    """Returns the index ordering (starting fixed at index 0) that
    minimizes total travel time, per EXACT_SOLVE_LIMIT above."""
    n = len(matrix)
    remaining = list(range(1, n))

    if n <= EXACT_SOLVE_LIMIT:
        best_order, best_cost = None, None
        for perm in permutations(remaining):
            order = [0, *perm]
            cost = sum(matrix[order[i]][order[i + 1]] for i in range(len(order) - 1))
            if best_cost is None or cost < best_cost:
                best_order, best_cost = order, cost
        return best_order

    # Nearest-neighbor fallback for larger days.
    order = [0]
    remaining_set = set(remaining)
    while remaining_set:
        last = order[-1]
        nxt = min(remaining_set, key=lambda j: matrix[last][j])
        order.append(nxt)
        remaining_set.remove(nxt)
    return order


def optimize_route(places: List[str]) -> Tuple[List[str], List[Dict[str, Any]]]:
    if len(places) < 2:
        return places, []

    matrix = _fetch_duration_matrix(places)
    order = _best_order(matrix)
    ordered_places = [places[i] for i in order]

    legs = [
        {
            "from": ordered_places[i],
            "to": ordered_places[i + 1],
            "mode": "driving",
            "duration_min": matrix[order[i]][order[i + 1]],
        }
        for i in range(len(ordered_places) - 1)
    ]
    return ordered_places, legs
