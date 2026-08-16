# AI Assist for Travellers — Frontend Boilerplate

A single-page Next.js app that drives the backend pipeline described in
[`../backend/README.md`](../backend/README.md). It doesn't call any
travel APIs itself — it only talks to the FastAPI backend, which is where
all the agent logic and (eventually) real Duffel/Amadeus/Google Maps
integrations live.

## Where everything lives

```
frontend/
  app/
    page.tsx            The whole conversation — transcript + composer, and
                          the switch that maps each pipeline stage to a block
    layout.tsx            Root HTML shell + page title
    globals.css             Design tokens (light/dark) + animations

  components/
    ChatMessage.tsx      One turn: user bubble, or assistant text + rich block
    DestinationCards.tsx   Agent 0's candidates: photo, rating, Maps link; multi-select
    ItineraryCompare.tsx    Agent 3's side-by-side day plans, one column each
    FlightList.tsx           Agent 1's flights, sortable by price/duration/time
    BudgetSplit.tsx          Optional flights-vs-hotel budget override
    HotelList.tsx             Agent 2's hotels: photo, rating, amenities, reviews link
    TripSummary.tsx            Final: booking, stay + link, routed day plan

  lib/
    types.ts              Types mirroring the backend's request/response shapes
    api.ts                  The only file that does `fetch()` against the backend
    maps.ts                   Builds Google Maps links for itinerary places
```

**Rule of thumb for making changes:** how the flow branches → `app/page.tsx`.
what one stage looks like → its component. what a request/response looks
like → `lib/types.ts`. how a request is sent → `lib/api.ts`.

## How it works

It's a chat, but not a general-purpose one — the backend drives. Every
response names a `stage`, and `page.tsx` maps that stage to the block it
renders (`agent0_choose` → destination cards, `agent1_approve` → the
sortable flight list, and so on).

Interaction is **dual-mode by design**: the user can click a card *or*
type an answer, and both go to the same endpoint. A click sends a
structured `selection` the backend trusts verbatim; typed text goes
through the LLM parsers in `../backend/app/services/nlu.py`. That's why
"book the cheapest one" and clicking **Book** on the cheapest row do the
same thing.

The transcript is append-only — nothing is replaced as the pipeline
advances, so the full history stays readable. Once a turn is answered its
block freezes, so old cards can't be clicked again and re-send a stale
choice.

### Images come from two different places

Hotel images are plain Google CDN URLs and go straight into `<img>`.
Destination photos **cannot** — Places photo URLs embed the Maps API key,
so they're fetched through the backend's `/photo` proxy via `photoUrl()`
in `lib/api.ts`. The frontend only ever holds the opaque `photo_ref`;
never build a Places photo URL here.

Both use plain `<img>` rather than `next/image`: one is already proxied
through our own origin and the other would need its remote host
allow-listed in `next.config.mjs`, so the optimizer buys nothing here.

### Sorting is client-side on purpose

`FlightList` and `HotelList` sort options already held in state. They must
never re-fetch: a new search returns *different* offer IDs than the ones
on screen, which would break the booking. See the replay-safety note in
`../backend/app/agents/agent1_flights.py`.

## Setup

Requires the backend running first — see `../backend/README.md`.

```bash
cd frontend
npm install
copy .env.local.example .env.local     # defaults to http://127.0.0.1:8000
npm run dev
```

Open http://localhost:3000. Try the exact vague-input case from the PRD —
destination `"a hill station"`, dates `"anytime between July and
December"` — and you should see Agent 0's clarifying questions appear
before anything else runs.

## Plugging in real APIs

This frontend never needs to know about Duffel, Amadeus, or Google Maps —
those integrations belong in the backend's `app/services/` stubs. Once
you replace a stub there with a real call, the frontend picks up the
richer data automatically (e.g. more flight fields) as long as you update
the matching interface in `lib/types.ts`.

## Known simplifications in this boilerplate

- No auth/session — a browser refresh loses the current trip's
  `thread_id` and drops you back to the start form. Fine for local dev;
  persist `thread_id` (e.g. in the URL or localStorage) before shipping.
- No calendar OAuth flow — the "use my calendar" checkbox just sets
  `calendar_connected: true`, which the backend's stub calendar service
  reads without actually authenticating anything.
- Styling is plain Tailwind utility classes, no design system — swap in
  shadcn/ui or similar once the flow itself is settled.
