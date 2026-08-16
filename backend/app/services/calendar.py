"""
Calendar integration stub (PRD FR2, Agent 0's optional input).

Real version: OAuth against Google Calendar (add
GOOGLE_CALENDAR_CLIENT_ID/SECRET in app/config.py), then read free/busy
blocks for the relevant date range via the Calendar API.
"""
from typing import Dict, List


def get_free_slots(date_query: str) -> List[Dict[str, str]]:
    """TODO: replace with a real Google Calendar freebusy.query call."""
    return [{"start": "2026-10-05", "end": "2026-10-12"}]
