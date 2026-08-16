# AI Assist for Travellers — Backend Boilerplate

Implements the pipeline described in [`../PRD.md`](../PRD.md): a sequential,
5-agent trip planner built with **FastAPI + LangGraph**, using an LLM
(currently Groq/Llama 3.3) for the reasoning steps.

Order is **0 → 3 → 4 → 1 → 2**: the user compares real itineraries and
locks in a destination *before* anything gets booked against it.

The API is conversational — the client sends free-text messages and the
server replies with what to say next plus rich content to render.

## Where everything lives

```
backend/
  app/
    main.py            FastAPI app — the graph endpoints, plus the /photo proxy
    orchestrator.py     Wires agent0..agent4 into one sequential graph (pipeline ORDER lives here)
    state.py             TripState — the shared object every agent reads/writes
    config.py             Loads API keys from .env

    agents/               One file per agent, each with a `run(state) -> dict` function
      agent0_best_time.py   Researches candidate destinations + best windows, user shortlists
      agent3_itinerary.py    Itinerary per shortlisted place, user compares and picks one
      agent4_routing.py       Google Maps route optimization per day
      agent1_flights.py        Asks origin, searches flights, books on approval
      agent2_hotels.py          Hotel search; booking is deep-link only

    services/              External-API stubs — swap the body, keep the signature
      reviews.py             Agent 0's destination research (LLM + Places verification)
      nlu.py                  Parses the user's free-text chat replies at each stage
      calendar.py              Agent 0's optional calendar integration
      flights_api.py            Agent 1's provider (Duffel)
      hotels_api.py               Agent 2's provider (SerpApi Google Hotels)
      maps_api.py                   Agent 4's provider (Google Distance Matrix)
      llm.py                          Shared LLM clients (Groq + Anthropic)
      budget.py                        Budget Allocator (PRD section 6)
```

**Rule of thumb for making changes:** pipeline *order* → `orchestrator.py`.
what one agent *does* → its file under `agents/`. where its data *comes
from* → the matching file under `services/`. shared fields every agent can
read/write → `state.py`.

## How the pipeline is sequential (and pausable)

`orchestrator.py` encodes the whole flow as a straight-line graph:

```
START
  -> agent0_research          find candidate destinations + best windows
  -> agent0_choose            [pause] user shortlists places to compare
  -> agent3_build             one itinerary per shortlisted place
  -> agent3_choose            [pause] user compares, locks the destination
  -> agent4_routing           optimise the winning itinerary's routes
  -> agent1_ask_budget        [pause] optional flights-vs-hotel budget split
  -> agent1_ask_origin        [pause] where are you flying from?
  -> agent1_search            find flights
  -> agent1_approve_and_book  [pause] user picks, agent books
  -> agent2_search            find hotels
  -> agent2_approve           [pause] user picks, gets booking link
  -> END
```

Each `[pause]` is a LangGraph `interrupt()` inside the agent, which stops
the graph and hands a payload back to the API caller. The graph resumes
exactly where it left off when the caller sends the next message.

So `POST /trips` doesn't plan a whole trip in one call — it runs until the
pipeline either completes *or* pauses, and you keep calling
`POST /trips/{id}/message` until you get `"status": "done"`.

### Why every stage is split into two nodes

Notice each agent that shows options has a *produce* node and a separate
*pause* node (`agent1_search` / `agent1_approve_and_book`). That split is a
**correctness requirement, not a style choice**.

LangGraph replays a node's code from the top on every resume. If a
non-deterministic call (an LLM request, a live flight search) sat in the
same node as the `interrupt()`, resuming would re-run it and get *different
results* — different flight offer IDs, a different candidate list — than
the ones the user was actually looking at when they chose. At best the
chosen ID is no longer found; at worst you book something the user never
saw.

Splitting means the produce step is checkpointed into `TripState` **before**
the pause, so replaying the pause step re-reads the same persisted data.
Follow this pattern for any new stage. See `agent1_flights.py` for the
full write-up.

## Talking to it

```bash
# Start — one free-text message, no structured fields.
curl -X POST http://127.0.0.1:8000/trips   -H "Content-Type: application/json"   -d '{"message": "cherry blossoms in north east India, 4-5 days, budget 30000 for 2"}'
```

Every reply has this shape:

```json
{
  "thread_id": "...",
  "status": "waiting_on_user",
  "prompt": {
    "stage": "agent0_choose",
    "text": "Here's what I found. Which of these...",
    "data": { "candidates": [ ... ] }
  }
}
```

`text` is what the assistant says; `data` is the rich content the frontend
renders (destination cards, itineraries, flight lists). Reply with either
free text, a structured `selection`, or both:

```bash
curl -X POST http://127.0.0.1:8000/trips/<thread_id>/message   -H "Content-Type: application/json"   -d '{"message": "compare Shillong and Tawang"}'

# ...or the equivalent click:
curl -X POST http://127.0.0.1:8000/trips/<thread_id>/message   -H "Content-Type: application/json"   -d '{"message": "", "selection": {"destinations": ["Shillong", "Tawang"]}}'
```

A `selection` is trusted verbatim; free text goes through the LLM parsers
in `services/nlu.py`. If a reply can't be understood, that stage re-asks
rather than guessing.

Keep going until `"status": "done"`, which returns the full `TripState`.

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # fill in keys later — not required to run the boilerplate
```

## Run

```bash
uvicorn app.main:app --reload
```

Interactive API docs: http://127.0.0.1:8000/docs

## Images and reviews

Destination cards and hotel cards both carry a photo, rating and review
count, and link out to the real listing. Neither costs an extra API call:

- **Destinations** — `reviews.look_up_place()` already calls Places Text
  Search to verify the LLM didn't hallucinate the place, so the photo and
  rating come back in that same response.
- **Hotels** — SerpApi returns `images`, `overall_rating`, `reviews`,
  `hotel_class` and `amenities` in the search response already.

**Itinerary places are the exception**: they get a plain Google Maps search
link, built client-side in `frontend/lib/maps.ts`, with no API lookup. A
comparison can hold ~30 places across two destinations, so enriching each
would mean dozens of billed calls and a visible stall for a link that
works fine without them.

### The /photo proxy, and why it exists

`GET /photo?ref=<photo_reference>` streams a Places photo through the
backend. Places photo URLs require the Maps API key as a query parameter,
so if the frontend built them directly **the key would be visible in
DevTools on every card**. The browser only ever receives the opaque
`photo_ref`. Responses are cached for a day since photo bytes for a given
ref don't change (and Places bills per request).

Hotel images skip the proxy — they're plain Google CDN URLs from SerpApi
that need no key.

## Which integrations are real

Live, hitting real APIs (keys in `.env`):

| Service | Provider | Notes |
|---|---|---|
| `llm.py` | **Groq** (Llama 3.3) | Used by agent0's specificity check, `reviews.py`, agent3. `ask_claude` also exists but the Anthropic account has no credits — Groq is what actually runs |
| `reviews.py` | Groq + Google Places | LLM suggests destinations, Places verifies they exist |
| `flights_api.py` | Duffel (test mode) | Real search + real bookings, no real money |
| `hotels_api.py` | SerpApi Google Hotels | Real search; booking is deep-link only |
| `maps_api.py` | Google Distance Matrix | Real travel times + route ordering |

Still stubbed: `calendar.py` (returns a fixed free slot — needs the Google
Calendar OAuth flow, which also needs frontend work).

## Known simplifications (see PRD section 12)

- **Placeholder passenger data on flight bookings.** `flights_api.book()`
  sends a hardcoded demo passenger; a real product must collect actual
  traveller details before ticketing.
- **Currency is not normalised — the budget maths is wrong across
  currencies.** The user's budget is whatever number they typed (often INR),
  Duffel returns fares in EUR, and SerpApi hotel rates are requested in USD.
  `budget_remaining` subtracts them raw, so a 30000 (INR) budget minus an
  81 EUR flight yields 29919, which means nothing. Everything must be
  converted to one currency (and the budget's own currency detected) before
  these figures can be trusted. Prices shown per-option are correct; only
  the arithmetic across them is not.
- **Agent 0 always takes the researched window for the first shortlisted
  destination** unless the user states dates. Letting them pick among
  `candidate_destinations`' windows needs another `interrupt()` gate — build
  it as its own node, see the replay-safety note in `agent1_flights.py`.
- **No budget-reallocation feedback loop** yet (PRD Phase 4) — `budget.py`
  does a one-time fixed split.
- **`MemorySaver` checkpointer is in-process** and wiped on restart — fine
  for local dev, swap for a Postgres/Redis checkpointer before deploying.

### Gotcha: stale server serving old code

`uvicorn --reload` can leave an orphaned worker holding the port after its
parent dies, so requests get served by *old* code while the file on disk is
new. If a change seems not to apply, check for more than one listener:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select ProcessId, CommandLine
```

Kill any uvicorn process older than your last edit, then restart.
