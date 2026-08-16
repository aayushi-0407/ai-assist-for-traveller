"""
FastAPI entrypoint — the only place that talks to the LangGraph pipeline
directly. The API is conversational: the client sends messages, the server
replies with either the next thing to say, or the finished trip.

    POST /trips                 start a trip from the user's opening message
    POST /trips/{id}/message    send the next message in that conversation

Both return one of:
    {"status": "waiting_on_user", "prompt": {stage, text, data}}
        The pipeline paused. `text` is what the assistant says; `data`
        carries whatever rich content that stage renders (destination
        cards, itineraries, flight lists...). Reply via /message.
    {"status": "done", "trip": {...}}
        Pipeline finished; `trip` is the full TripState.

Clients may answer with free text, a structured `selection` (from clicking
a card), or both — see services/nlu.py for how each stage interprets them.

Run locally with:  uvicorn app.main:app --reload
"""
import logging
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from langgraph.types import Command
from pydantic import BaseModel

from app.config import settings
from app.orchestrator import build_graph

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Assist for Travellers")

# --------------------------------------------------------------------------
# MIDDLEWARE ORDER MATTERS — do not reorder these two blocks.
#
# Starlette's add_middleware() INSERTS AT THE FRONT, so the LAST one
# registered ends up OUTERMOST. The error handler therefore has to be
# registered FIRST so it sits *inside* CORS: it catches the exception,
# returns a normal response, and that response then travels back out
# through CORSMiddleware, which attaches the CORS headers.
#
# Get this backwards (or use @app.exception_handler(Exception), which
# Starlette hoists into ServerErrorMiddleware, outside everything) and
# failed requests reach the browser with no CORS headers — so it reports a
# useless "Failed to fetch" and the real error message is invisible.
# --------------------------------------------------------------------------


@app.middleware("http")
async def surface_errors_with_cors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        logger.exception("Request to %s failed", request.url.path)
        return JSONResponse(status_code=500, content={"detail": str(exc)})


# Registered last => outermost, so it wraps the handler above.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


graph = build_graph()


class StartTripRequest(BaseModel):
    message: str            # the user's opening free-text message


class MessageRequest(BaseModel):
    message: str = ""
    selection: Optional[Dict[str, Any]] = None   # set when the user clicked instead of typed


def _format_response(thread_id: str, result: dict) -> dict:
    """graph.invoke() returns either a normal state dict, or one containing
    "__interrupt__" if a node paused. This is the single place that
    distinguishes the two, so both endpoints stay thin."""
    if "__interrupt__" in result:
        paused = result["__interrupt__"][0]
        return {"thread_id": thread_id, "status": "waiting_on_user", "prompt": paused.value}
    return {"thread_id": thread_id, "status": "done", "trip": result}


@app.post("/trips")
def start_trip(req: StartTripRequest) -> dict:
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # Only the raw message — no placeholder budget or traveller count.
    # Agent 0's intake establishes those from what the user actually said
    # (falling back to intake.FALLBACK_BUDGET only if they decline to name
    # a figure), and nothing downstream reads them before it runs.
    initial_state = {
        "opening_message": req.message,
        "calendar_connected": False,
    }

    result = graph.invoke(initial_state, config=config)
    return _format_response(thread_id, result)


@app.get("/photo")
def photo(ref: str, w: int = 640) -> Response:
    """Proxy a Google Places photo.

    Exists so the Maps API key never reaches the browser — rendering a
    Places photo requires the key in the URL, so if the frontend built
    these URLs itself the key would be visible in DevTools on every card.
    The frontend only ever holds the opaque `photo_ref`.
    """
    upstream = httpx.get(
        "https://maps.googleapis.com/maps/api/place/photo",
        params={"maxwidth": w, "photo_reference": ref, "key": settings.google_maps_api_key},
        timeout=20,
        follow_redirects=True,
    )
    if upstream.status_code != 200:
        return Response(status_code=upstream.status_code)

    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        # Photo bytes for a given ref never change, so let the browser keep
        # them rather than re-hitting Places (which is billed per request).
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/trips/{thread_id}/message")
def send_message(thread_id: str, req: MessageRequest) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(
        Command(resume={"message": req.message, "selection": req.selection}),
        config=config,
    )
    return _format_response(thread_id, result)
