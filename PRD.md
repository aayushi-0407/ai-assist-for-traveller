# PRD: AI Assist for Travellers

**Status:** Draft v1
**Owner:** Ayushi Singh
**Last updated:** 2026-08-11

---

## 1. Summary

AI Assist for Travellers is a web application that plans and books an entire trip — destination timing, flights, hotels, day-by-day itinerary, and in-trip navigation — within a traveller's stated **budget** and **available dates**. The system is powered by a multi-agent architecture, where each agent owns one stage of the trip-planning pipeline and hands its output to the next.

## 2. Problem Statement

Planning a trip today means juggling 5–10 tabs and tools: review sites to figure out *when* to go, flight search engines, hotel search engines, spreadsheets or notes apps for the itinerary, and maps for figuring out how to move between places once there. Each step is manual, and budget/date constraints aren't carried through — a traveller might book a great flight deal, then find hotels for those dates blow the budget, and have to start over. There's no single system that plans holistically against a fixed budget and fixed date window end-to-end.

## 3. Goals

<span style="background-color: #FFFFFF;"><span style="color: #FFFFFF;">hi </span></span>

- Let a user specify a **destination (or open to suggestions), budget, and date window (or flexible dates)**, and receive a complete, bookable trip plan.
- Optimize choices (timing, flights, hotels, itinerary, routing) jointly against the budget rather than independently.
- Reduce trip-planning time from hours/days of manual research to minutes.
- Support real booking, not just recommendations — the user should be able to complete flight and hotel bookings through the assistant.

### Non-Goals (v1)

- Visa/immigration document handling and compliance advice.
- Multi-traveller expense splitting. (Group trips themselves *are* supported to the extent that Agent 0 captures party type and several departure cities — but flights are only priced for one of those cities in v1; see Agent 1.)
- Loyalty/points program optimization (e.g. redeeming airline miles).
- Real-time in-trip re-planning due to disruptions (flight delays, cancellations) — treated as a future phase.
- Non-flight transport booking (trains, buses, car rentals) in v1.

## 4. Target Users

- **Primary persona: The time-constrained leisure traveller.** Has fixed vacation days and a budget ceiling, wants a good trip without spending a weekend researching it.
- **Secondary persona: The budget-flexible explorer.** Knows their budget and rough date window, is open to destination suggestions and wants the system to tell them where they can go and when.

## 5. High-Level User Flow

1. User describes the trip they want in a single free-text message ("cherry blossoms in north east India, 4-5 days, ₹30000 for 2"). **Agent 0** extracts budget, dates, party and origin(s) from it and shows them back as a prefilled brief, asking only for whatever is genuinely missing — plus how they'd like the budget divided, which is what tells the system whether they're after a relaxing trip or a busy one.
2. **Agent 0** then researches candidate destinations matching what the user described (including vague input like "somewhere with cherry blossoms"), each with why it fits and the best window to visit, cross-referenced with the user's calendar availability if connected. The user shortlists one or more to explore.
3. **Agent 3** builds a full day-by-day itinerary for *each* shortlisted destination, so the user can compare real plans side by side and lock in a final destination.
4. **Agent 4** takes the winning itinerary's places and produces an optimized route/order and travel directions (via Google Maps) for each day.
5. **Agent 1** asks where the user is flying from, then searches and proposes flight options within budget for the selected dates (sortable by price, duration, departure); user selects/approves; agent completes booking.
6. **Agent 2** searches and proposes hotel options for the remaining budget after flights; user selects one and receives a deep link to complete the booking.
7. User receives a final consolidated trip plan: bookings confirmed, day-by-day schedule with routes, and total spend vs. budget.

## 6. Budget as a Cross-Cutting Constraint

Budget is not a filter applied independently by each agent — it is a shared, shrinking resource passed through the pipeline:

- User sets total trip budget, at Agent 0's intake.
* A **Budget Allocator** (shared service, not a user-facing agent) proposes an initial split across flights / hotel / activities+food / buffer, using configurable heuristics (e.g. flights \~35%, hotel \~35%, itinerary/activities \~20%, buffer \~10%).
- **The user can set that split themselves at intake**, as percentages across three buckets they can actually reason about — travel / hotel / activities. The buffer is held back off the top and never offered as a choice; their percentages divide what's left. Percentages are normalised rather than validated, so numbers that don't add to 100 rescale instead of erroring.
- Each agent reports actual committed spend back to the Budget Allocator, which recalculates remaining budget for the next agent in the pipeline.
- **Before searching, a user who left the split on its default is shown it and can override it** — naming a specific amount for flights and/or the hotel. Whatever they don't pin absorbs the difference so the parts still sum to the total. Optional: the automatic split stands if they're happy with it.
- If an agent cannot find options within its allocated slice, it requests reallocation (e.g. flights came in cheaper than expected → more budget available for hotel), or flags to the user that the trip is not feasible within budget and suggests trade-offs (shorter trip, different dates, different destination).

## 7. Agent Specifications

### Agent 0 — Where to Go, and When
- **Input:** The user's free-text description of the trip, optional user calendar.
- **Function:**
  0. **Establish the four criteria first.** Before researching anything, Agent 0 fills a structured trip brief. Everything it can is extracted from the opening message; the user then confirms it in a single prefilled form (or in prose — both paths work). The four criteria are:

     | # | Criterion | Shape | Notes |
     |---|---|---|---|
     | 1 | **Destination** | set | Freeform description in, a *set* of candidates out; the user shortlists one or several. Never resolved to one here — that's Agent 3's job. |
     | 2 | **Source** | array | The party type is asked up front (individual / family / group), and if it's not an individual, whether everyone departs from the same place. If not, each departure city carries its own head count. |
     | 3 | **Travel window** | array | Either **fixed** — one or more specific slots the user commits to — or **flexible**, a month/season to place the trip inside. |
     | 4 | **Budget** | total + split | The total, plus optionally how it divides across **travel / hotel / activities** as percentages. |

     **Agent 0 does not hand off until all four are answered.** The intake step loops, re-asking each round, and the fields split into two tiers by whether a default exists:

     - **Required — no default, so the loop never gives up:** destination brief, at least one departure city, total budget. Researching against a blank destination or an unknown budget produces a shortlist that means nothing, so there is no version of "proceed anyway" worth having.
     - **Expected — chased, but conceded after two unproductive rounds:** party type, travel window, trip length, budget split. The loop tracks *progress*, not reply count, so a user who is answering is never cut off however many rounds it takes; a user who genuinely doesn't know gets the documented default applied and **told which assumption was made**, at the first screen where they can see its effect.

     This is what stops "keep asking until complete" from becoming a hung conversation on a question like "how many days?" that the user may simply not be able to answer yet.

     On the way out, the node asserts its own output contract — every field it promises downstream is present, or it fails loudly rather than handing Agent 3 a half-built trip.
  1. **Research, don't interrogate.** Vague input is the normal case, not an error — "a hill station", "somewhere with cherry blossoms", "I don't know where" are all directly actionable. Agent 0 turns the description into concrete candidate destinations rather than asking the user to name one. The intake step above is a confirmation of what they already said, not a questionnaire.
  2. **Read intent off the budget split.** How someone divides hotel vs. activities says what kind of trip they want without having to be asked: a heavy hotel share means a **relaxation** trip, a heavy activities share an **activity-led** one, and neither means **balanced**. That inference is fed into destination research and itinerary building. It's the reason criterion 4 is collected at granular level rather than as a single number.
  3. **Time each candidate.** With a *flexible* window, every candidate gets the window that genuinely suits it best inside the user's constraint — and those windows differ between candidates, which is the value of giving a flexible one. With *fixed* dates, every candidate is timed to exactly those dates instead, and says honestly what that place is like then, including when it's a poor time to visit. If the trip is tied to a seasonal event (cherry blossoms, a festival), the window is matched to it. If the user connects their calendar, windows are cross-referenced against actual free dates.
  4. **Verify.** Each suggested place is checked against Google Places so a hallucinated or misspelled name can never reach flight search.
- **Output:** The filled trip brief (destinations set, origins array, travel window(s), budget + split + inferred trip style), plus a shortlist of candidate destinations — each with a photo, star rating and review count from Google Places, why it fits *this* traveller's actual situation, a concrete ISO date window, a note on why that's the right time, and a link through to the full listing and reviews. The user picks one *or several* to compare.
- **Data sources:** LLM reasoning for suggestions/seasonality, Google Places for existence verification, optionally Google/Outlook Calendar (read-only, user-authorized).
- **Calendar integration is optional** — if not connected, recommendations are destination-based only.
- **Agent 0 deliberately does not resolve a single destination.** That decision belongs to Agent 3's comparison step, once the user can see what each option's days actually look like.

### Agent 1 — Flight Search & Booking
- **Input:** Destination and dates (already fixed by Agent 3), passenger count, budget slice, and the origins array from Agent 0's intake. Agent 1 no longer asks for the origin in the normal flow — it only does so as a fallback, e.g. after a mid-flow change of destination.
- **Multi-origin limitation (v1):** Agent 0 captures every departure city, but Agent 1 prices a **single** route — the origin with the most travellers. Remaining legs are shown as explicitly unpriced rather than silently omitted from the total. Fanning the search out per origin group and summing against the flight budget slice is the follow-on work.
- **Budget:** if the user set their own travel/hotel/activities split at intake, Agent 1 skips its own budget question rather than asking twice. Someone who left the split on the allocator's default still gets asked here, in absolute amounts, now that they know where they're going.
- **Function:** Searches flights across providers and presents the options with price, duration, stop count and times, **sortable by price / duration / departure** so the user can rank them however they care to. Executes booking on confirmation. The search half runs early and in parallel (see Section 8); only the booking waits for the user's destination choice.
- **Round trip:** two slices — out on the window's start, back on its end — so the flight has a return date the hotel checkout is reconciled against. A route with no round-trip inventory falls back to one-way and is labelled as such rather than silently dropping the return.
- **Party fares:** one passenger per traveller, so the quoted price is what the whole party pays. Comparing a single seat against a party budget made every trip look affordable.
- **Output:** Booked flight (confirmation, PNR) or, if nothing fits budget, best-available options with the gap flagged.
- **Data sources:** Flight search/booking API (e.g. Amadeus, Skyscanner, or airline-direct APIs).

### Agent 2 — Hotel Search & Deep-Link Booking
- **Input:** Destination, check-in/check-out dates, budget slice, traveller count, optional preferences (rating, location/neighborhood).
- **Function:** Searches hotels and presents each with a photo, star rating, review count, hotel class, location score and key amenities, **sortable by price or rating**, plus a link to the full reviews — enough to compare properly without leaving the chat. Unlike Agent 1, this agent does **not** complete the booking itself — the user selects an option and is handed a deep link to finish booking on the provider's own site.
- **Output:** A selected hotel option plus a booking link (no in-app confirmation/PNR, since the booking itself happens off-platform).
- **Data sources:** SerpApi's Google Hotels API (search/aggregation with instant self-serve access).
- **Why search-only instead of full booking (see Section 12):** the hotel booking APIs originally scoped here (Amadeus, Hotelbeds) both require a partner/enterprise application with no instant self-serve tier — Amadeus discontinued its free self-service developer portal entirely. Flights (Agent 1, via Duffel) remain fully self-serve bookable; only the hotel leg is deep-link-only until a real hotel booking partnership is in place.

### Agent 3 — Itinerary Builder & Destination Decision
- **Input:** The shortlisted destinations from Agent 0, trip dates/length, remaining budget, the trip style inferred from Agent 0's budget split, optional user interests (e.g. food, history, nature, nightlife).
- **Function:** Generates a day-by-day plan for **each** shortlisted destination — real named places, grouped so a day's stops are near each other (Agent 4 then routes them). Day density follows the trip style: a relaxation-weighted budget gets at most 2 stops a day with room to do nothing, an activity-weighted one gets 3–4. The user compares the plans side by side and picks the one they want, which locks in the destination for booking.
- **Output:** One itinerary per shortlisted destination, plus the user's final chosen destination and its itinerary.
- **Why this runs before booking:** comparing real itineraries is *how* the user decides where to go, so it has to happen before Agent 1/2 book anything against that decision.
- **What the comparison now shows:** because Agents 1 and 2 searched in parallel, each destination's column carries its itinerary *and* its flight price, hotel total, trip total against budget, and the reconciled dates — including a note when those dates had to move to find availability. Destinations with no bookable window are shown but not selectable.

### Agent 4 — Route Optimization (Google Maps Integration)
- **Input:** Each day's list of places from Agent 3.
- **Function:** Given a set of places to visit in a day, computes the most efficient visiting order and route (minimizing travel time/distance), using Google Maps Directions/Distance Matrix APIs. Handles the classic "N places, best order" (TSP-like) routing problem for small N.
- **Output:** Ordered day plan with travel mode, times, and turn-by-turn/route links between each stop.

## 8. Agent Orchestration

- A central **Orchestrator** sequences agent calls, passes context (dates, budget remaining, location) between them, and holds the shared trip state. The shape is **0 → (3 ∥ 1+2 search) → 4 → 1 book → 2 select**.
- **Agent 0 runs as three stages: extract → intake [pause] → research → choose [pause].** Criteria intake deliberately precedes research: party size, departure city and budget all change which destinations are worth suggesting at all, so researching first and asking afterwards means throwing the answers away.
- **Agents 1, 2 and 3 fan out in parallel once Agent 0 has the shortlist.** Nothing Agent 3 needs depends on Agents 1/2 and vice versa — all three want the same shortlist and nothing else — so running them in sequence only made the user wait through three round trips for something they could be told at once. Both branches join at Agent 3's comparison step, which therefore shows each destination's itinerary, real total price and actually-bookable dates together.
- **Search fans out; booking does not.** Searching every shortlisted destination is cheap and reversible, so it happens up front. Booking is neither, so it stays behind the user's destination choice — the parallel branch only ever searches.

### Flight/hotel date reconciliation

Agents 1 and 2 cannot search independently, because their answers have to describe the same trip: a flight on 1 Aug returning 7 Aug is worthless if nothing has a room those nights. So their search halves run as one joint step per destination:

1. Search flights and hotels **for the same candidate window**, concurrently.
2. If both have inventory, that's the window — it becomes the trip's dates, and the flight's outbound/return match the hotel's check-in/check-out exactly.
3. If either side is empty, shift the window (keeping the trip's length) and retry — up to 3 probes at 0, ∓3 days.
4. If no probe works, the destination is reported unbookable **with which side was missing** ("flights available, nowhere to stay"), stays visible in the comparison so its itinerary can still be read, but cannot be chosen.

**Fixed dates are never shifted.** If the user pinned specific dates at intake, moving them to find inventory would silently rebook their trip around the hotel market; they get told the clash instead. Shifting only applies to a flexible window, where the exact week was ours to pick in the first place.

Probe count and the per-plan destination cap are deliberately small: each probe is one SerpApi call per destination against a 100-search monthly tier, so an unbounded hunt would exhaust it on a single trip.
- **Itinerary planning deliberately runs before booking.** The user decides *which* destination by comparing real day-by-day itineraries, so nothing can be booked until that comparison happens; Agents 1 and 2 then book against the chosen destination.
- Each agent stage requires **user confirmation** before committing an irreversible action (booking flights/hotels cost real money) — agents propose, user approves, agent executes.
- Agents run independently enough to be individually re-invoked (e.g. user changes hotel after itinerary is built → Agent 3/4 re-run with new hotel location) without restarting the whole pipeline.

## 9. Functional Requirements

| # | Requirement |
|---|---|
| FR1 | User can input budget, date window (fixed or flexible), and destination (fixed or open) |
| FR1a | User can state who's travelling (individual / family / group) and how many |
| FR1b | User can give multiple departure cities, each with its own head count, when the party doesn't set off from one place |
| FR1c | User can give either fixed date slots (one or more) or a flexible month/season window |
| FR1d | User can set what share of the budget goes to travel / hotel / activities, and the system reads trip intent (relaxation vs. activity-led) off that split |
| FR2 | User can optionally connect a calendar (Google/Outlook) for availability-aware date suggestions |
| FR3 | System recommends best travel dates with rationale, when destination is fixed but dates are flexible |
| FR4 | System suggests destinations, when destination is open but dates are fixed |
| FR5 | System searches and displays flight options within the allocated budget, sortable/filterable |
| FR6 | User can complete flight booking through the app |
| FR7 | System searches and displays hotel options within the allocated budget |
| FR8 | User can select a hotel option and follow a deep link to complete booking on the provider's site |
| FR9 | System generates a day-by-day itinerary respecting trip length and remaining budget |
| FR10 | User can edit/regenerate itinerary items (swap an activity, remove a day) |
| FR11 | System computes an optimized daily route across selected places via Google Maps |
| FR12 | System shows running total spend vs. budget at every stage |
| FR13 | System flags and explains when budget/date constraints cannot be met, with suggested trade-offs |
| FR14 | User receives a consolidated final trip plan (bookings + itinerary + routes) exportable/shareable |
| FR15 | Itinerary building and flight/hotel search run concurrently across the whole shortlist, so the comparison shows plans and prices together |
| FR16 | Flight dates and hotel dates always describe one window; if either side has no inventory the window shifts (flexible dates only) until both do |
| FR17 | A destination with no bookable window is shown with its itinerary, labelled with which side was unavailable, and excluded from selection |

## 10. Non-Functional Requirements

* **Latency:** Flight/hotel search results returned in under \~10s per query; itinerary generation under \~15s.
- **Reliability:** Booking actions must be idempotent/confirmable — no duplicate charges on retry.
- **Security & privacy:** Calendar access is OAuth-based, read-only, revocable; payment details handled via PCI-compliant third-party booking providers, never stored directly.
- **Auditability:** Every booking action taken by an agent is logged with the option shown, price, and explicit user confirmation timestamp.
- **Extensibility:** Agents are modular enough that a new agent (e.g. train booking, visa checks) can be added to the pipeline without rework of existing agents.

## 11. Success Metrics

- Time from "start planning" to "fully booked trip with itinerary" (target: under 30 minutes for a straightforward trip).
- % of trips planned that stay within stated budget.
- Booking completion rate (proposed flight/hotel → actually booked).
- User satisfaction / itinerary edit rate (lower edit rate suggests better first-pass itinerary quality).

## 12. Key Risks & Open Questions

- **Provider access (resolved for hotels, decided 2026-08-01):** confirmed Amadeus's self-service developer portal has been discontinued and Hotelbeds/Booking.com require a partner application — no instant self-serve hotel *booking* access exists for an indie project. Agent 2 was descoped to search + deep-link (see Section 7) using SerpApi's Google Hotels API, which does offer instant self-serve access for search. Revisit full in-app hotel booking once a real partnership is secured. Flights (Duffel) are unaffected and remain fully self-serve bookable.
- **Budget allocation heuristics:** Initial flight/hotel/activity split percentages are a guess and should be tunable/learned over time. The user can now override them at intake, which also gives a signal to learn from.
- **Multi-origin flight pricing:** Agent 0 captures every departure city, but Agent 1 prices only the largest group's route. Fanning out one search per origin and summing against the flight budget slice needs a decision on how a partial over-budget result is presented — is the trip infeasible, or just one leg?
- **Fixed dates at a bad time:** when the user pins dates that are a poor season for a candidate, Agent 0 says so in the season note but still offers the place. Whether it should instead rank those candidates down, or warn harder, is unresolved.
- **Review data quality:** Agent 0's "best time to travel" quality depends heavily on review/seasonality data source — needs a concrete data source decision.
* **Route optimization at scale:** Agent 4's routing is straightforward for \~5 stops/day; needs a defined approach (exact TSP vs. heuristic) if stop counts grow.
- **Payments/liability:** Who is the merchant of record for bookings — the assistant, or does it always hand off to the provider's own checkout? This affects PCI scope significantly.
- **Calendar integration:** Confirm which calendar providers to support at launch (Google Calendar only, or also Outlook/Apple).

## 13. Phased Rollout (suggested, within full-vision scope)

1. **Phase 1:** Orchestrator + Agent 0 (best time) + Agent 3 (itinerary), no live booking — validates planning quality first.
2. **Phase 2:** Agent 1 + Agent 2 live search and booking integration.
3. **Phase 3:** Agent 4 Google Maps route optimization layered onto itineraries.
4. **Phase 4:** Budget Allocator feedback loop (reallocation across agents), calendar integration, trade-off suggestions.

## 14. Proposed Tech Stack

**Frontend:** Next.js (React + TypeScript) + Tailwind + shadcn/ui. Fast to build a clean trip-planning UI, deploys easily on Vercel, and server actions cover simple API calls without a separate BFF layer.

**Backend / Agent Orchestration:** Python + FastAPI, with **LangGraph** as the orchestrator.
- LangGraph fits the pipeline pattern described in Section 8: a stateful graph (Agent 0 → 1 → 2 → 3 → 4) with conditional branches (budget reallocation, re-running Agent 3/4 when the hotel changes) and built-in support for **human-in-the-loop approval gates** — required before every booking action per FR6/FR8.
- LLM: **Groq (Llama 3.3)** for all agent reasoning, called in JSON mode at temperature 0 wherever the output is parsed (unconstrained output occasionally emits malformed JSON and breaks the pipeline at runtime). Claude (Anthropic API) is wired up as an alternative in `llm.py` but is currently unused — the project's Anthropic account has no billing credits. Groq's free tier removed that blocker.

**Database:** PostgreSQL for trip state, bookings, and budget-allocation records; Redis for caching search results (flight/hotel queries) and session state between agent steps.

**External APIs (per agent):**

| Agent | Suggested API | Notes |
|---|---|---|
| 0 – Best time | **Groq (Llama 3.3)** for destination suggestion + seasonality reasoning, Google Places to verify suggestions exist | Note: Places Text Search cannot be used to *find* destinations from a descriptive query — it returns location-biased attractions near the caller instead. The LLM handles intent; Places only confirms a suggested place is real. A dedicated weather/seasonality API would ground this better than model knowledge |
| 0 – Calendar | Google Calendar API (OAuth, read-only) | Add Microsoft Graph later for Outlook |
| 1 – Flights | **Duffel** | Purpose-built for real self-serve booking (not just search) — simpler than Amadeus for completing an actual purchase |
| 2 – Hotels | **SerpApi Google Hotels API** (search only) + deep link to book | Amadeus's self-service tier was discontinued and Hotelbeds requires a partner application — neither offers instant self-serve booking access, so hotels are search + deep-link only until a real booking partnership is secured (see Section 12) |
| 3 – Itinerary | Groq (Llama 3.3) | Must emit full geocodable place names ("Umiam Lake, Shillong"), since Agent 4 feeds them straight into Distance Matrix |
| 4 – Routing | Google Maps Directions + Distance Matrix API | As scoped in Agent 4 (Section 7) |

**Payments:** Route through Duffel/Amadeus's own checkout rather than handling cards directly — keeps the system out of PCI scope, resolving the open question in Section 12.

**Infra:** Docker containers; frontend on Vercel, backend on Fly.io or Render (both support long-running async agent calls without the operational overhead of AWS/Kubernetes at this stage). Add LangSmith for tracing agent runs, useful for debugging a 5-agent pipeline.

**Key tradeoff:** an all-TypeScript alternative (Node backend, orchestration via the Claude Agent SDK or a hand-rolled state machine instead of LangGraph) avoids a language switch between frontend and backend, but gives up LangGraph's maturity around conditional, human-in-the-loop graphs — the trickiest part of this system to get right.
