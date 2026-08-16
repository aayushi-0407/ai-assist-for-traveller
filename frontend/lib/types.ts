/**
 * Mirrors the backend's contract exactly (see ../backend/app/main.py and
 * ../backend/app/state.py). Nothing enforces this link automatically — the
 * two are separate processes — so if a backend field name changes, change
 * it here too.
 */

// --- Agent 0's four planning criteria (backend app/services/intake.py) ---

export type PartyType = "individual" | "family" | "group";

/** "fixed" = specific dates they've committed to; "flexible" = a month or
 *  season to fit the trip inside, leaving research free to pick the best
 *  week per destination. */
export type DateMode = "fixed" | "flexible";

/** One departure point. A group converging from several cities has several
 *  of these; `travellers` is how many people set off from that one. */
export interface OriginGroup {
  city: string;
  travellers: number;
}

/** How the total divides. Sent as percentages — the backend normalises,
 *  so they don't have to add up to exactly 100. */
export interface BudgetSplitPref {
  travel: number;
  hotel: number;
  activities: number;
}

/** The working draft the intake form edits. Nulls are genuine unknowns:
 *  they're what the form highlights as still needed. */
export interface IntakeCriteria {
  destination_query: string | null;
  party_type: PartyType | null;
  same_origin: boolean | null;
  origins: OriginGroup[];
  travellers: number | null;
  date_mode: DateMode | null;
  date_query: string | null;
  trip_days: number | null;
  budget_total: number | null;
  budget_split_pref: BudgetSplitPref | null;
}

/**
 * One destination's joint flight+hotel result (backend
 * services/availability.py). `window` is the reconciled one — the dates
 * where BOTH sides had inventory, which may not be the window research
 * originally picked; `shifted_by` says how far it moved to get there.
 */
export interface DestinationAvailability {
  destination: string;
  available: boolean;
  window: { start: string; end: string };
  shifted_by: number | null;
  /** Which side was empty when nothing worked: flights, hotels, or both. */
  blocked_by: "flights" | "hotels" | "both" | "error" | null;
  windows_tried: { start: string; end: string }[];
  nights: number;
  cheapest_flight: number | null;
  cheapest_hotel_night: number | null;
  hotel_total: number | null;
  trip_total: number | null;
  fits_budget: boolean;
  flights_fit: boolean;
  hotel_fits: boolean;
}

// --- Rich payloads, one per pipeline pause ---

export interface Candidate {
  name: string;
  why: string;
  window: string;
  start: string;
  end: string;
  season_note?: string;
  // Enrichment from Google Places (see backend reviews.look_up_place).
  // `photo_ref` is an opaque reference, not a URL — render it through
  // photoUrl() in lib/api.ts so the Maps key stays on the server.
  photo_ref: string | null;
  rating: number | null;
  review_count: number | null;
  maps_url: string | null;
  address: string | null;
}

export interface DayPlan {
  day: number;
  title?: string;
  places: string[];
  est_cost: number;
}

export interface RouteLeg {
  from: string;
  to: string;
  mode: string;
  duration_min: number;
}

export interface RoutedDayPlan extends DayPlan {
  route_legs: RouteLeg[];
}

export interface FlightOption {
  id: string;
  carrier: string;
  /** Whole-party fare, ALWAYS in INR — flights_api sends one passenger per
   *  traveller and converts the airline's quote before emitting it. */
  price: number;
  currency: string;
  /** What the airline actually quoted, kept for transparency. */
  quoted_price?: number;
  quoted_currency?: string;
  /** True when the rupee figure came from a fallback rate because the live
   *  FX endpoint was unreachable (backend services/fx.py). */
  fx_approximate?: boolean;
  departing_at: string;
  arriving_at: string;
  /** Outbound slice only, so "fastest" sorting stays meaningful. */
  duration_min: number;
  stops: number;
  origin: string;
  destination: string;
  // Round-trip legs. `has_return` is false when the route had no
  // round-trip inventory and the search fell back to one-way — the return
  // is then unpriced rather than absent from the plan.
  has_return?: boolean;
  return_departing_at?: string;
  return_arriving_at?: string;
  return_stops?: number;
  // Which airport this actually flies into — may be a different city than
  // the destination (Tawang is reached via Guwahati), so it's shown.
  origin_airport?: string;
  destination_airport?: string;
  destination_city?: string;
}

export interface HotelOption {
  id: string;
  name: string;
  price: number;
  rating: number | null;
  booking_link: string;
  // Display-only enrichment, all from the same SerpApi search response.
  review_count: number | null;
  hotel_class: string | null;
  location_rating: number | null;
  amenities: string[];
  image: string | null;   // Google CDN URL, safe to use directly in <img>
  reviews_url: string;    // Google Maps listing, where the reviews live
}

// --- The "waiting_on_user" stages ---

export type PipelinePrompt =
  | {
      // Agent 0's criteria intake, before any research runs.
      stage: "agent0_intake";
      text: string;
      data: {
        criteria: IntakeCriteria;
        // Two tiers of gap (backend intake.REQUIRED / intake.EXPECTED).
        // `missing` has no fallback and the node will not exit without it;
        // `expected` is chased but conceded to a default if the user can't
        // answer, so it's a nudge rather than a block.
        missing: string[];
        expected: string[];
        party_types: PartyType[];
        default_split: BudgetSplitPref; // the allocator's recommendation
      };
    }
  | {
      stage: "agent0_choose";
      text: string;
      data: {
        candidates: Candidate[];
        // Set when the user committed to specific dates at intake, in
        // which case these override each candidate's own window.
        date_windows: { start: string; end: string; label?: string }[];
        date_mode: DateMode;
      };
    }
  | {
      stage: "agent3_choose";
      text: string;
      data: {
        itineraries: Record<string, DayPlan[]>;
        date_window: { start: string; end: string };
        // From the parallel availability branch: per destination, the
        // window where flights AND hotels both exist, and what it costs.
        availability: Record<string, DestinationAvailability>;
        // Destinations that can actually be booked. Anything outside this
        // is still shown (the itinerary is real) but can't be chosen.
        bookable: string[];
      };
    }
  | {
      // Nothing was available within the allotted budget — the user is
      // asked to raise it, then the graph re-searches.
      stage: "agent1_budget_short" | "agent2_budget_short";
      text: string;
      data: {
        allocated: number;
        cheapest: number;
        suggested: number;
        currency?: string;
      };
    }
  | { stage: "agent1_origin"; text: string; data: Record<string, never> }
  | {
      stage: "agent1_approve";
      text: string;
      data: { flights: FlightOption[]; budget: number };
    }
  | {
      stage: "agent2_approve";
      text: string;
      // `budget` is the whole-stay slice; `nights` lets the UI show a
      // room's stay total alongside its nightly rate.
      data: { hotels: HotelOption[]; budget: number; nights: number };
    };

// --- The full trip once the pipeline reaches "done" ---

export interface TripState {
  opening_message: string;
  destination_query: string;
  date_query: string;
  budget_total: number;
  budget_remaining: number;
  budget_allocation: Record<string, number>;
  travellers: number;
  // Agent 0's criteria, as resolved at intake.
  intake_criteria: IntakeCriteria;
  party_type: PartyType;
  same_origin: boolean;
  origins: OriginGroup[];
  date_mode: DateMode;
  date_windows: { start: string; end: string; label?: string }[];
  budget_split_pref: BudgetSplitPref;
  trip_style: "relaxation" | "activities" | "balanced";
  candidate_destinations: Candidate[];
  shortlisted_destinations: string[];
  selected_date_window: { start: string; end: string };
  trip_days: number;
  itinerary_options: Record<string, DayPlan[]>;
  resolved_destination: string;
  itinerary: DayPlan[];
  routed_itinerary: RoutedDayPlan[];
  origin: string | null;
  flight_options: FlightOption[];
  booked_flight: FlightOption & { confirmation: string };
  hotel_options: HotelOption[];
  // No confirmation — Agent 2 is search + deep-link only (PRD section 7).
  selected_hotel: HotelOption;
}

// Discriminated union on `status` — TypeScript narrows `prompt` vs `trip`
// automatically once you check `response.status`.
export type PipelineResponse =
  | { thread_id: string; status: "waiting_on_user"; prompt: PipelinePrompt }
  | { thread_id: string; status: "done"; trip: TripState };

/** What the intake form submits. Mirrors nlu.parse_intake_reply's
 *  `selection` branch, which trusts these verbatim — no LLM in the loop. */
export interface IntakeSelection {
  destination_query: string | null;
  party_type: PartyType;
  travellers: number;
  origins: OriginGroup[];
  date_mode: DateMode;
  date_query: string | null;
  trip_days: number | null;
  budget_total: number | null;
  budget_split_pref: BudgetSplitPref;
}

/** What a click (rather than typed text) sends back. Shapes match the
 *  parsers in ../backend/app/services/nlu.py. */
export type Selection =
  | IntakeSelection
  | { destinations: string[]; date_query?: string }
  | { destination: string }
  | { flights?: number | null; hotel?: number | null }
  | { origin: string }
  | { option_id: string };
