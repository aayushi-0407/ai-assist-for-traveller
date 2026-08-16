/**
 * Final screen once the backend returns status "done" — everything the
 * pipeline produced, in one place: booked flight, chosen hotel (with the
 * link to actually book it), and the route-optimised day plan.
 */
import { placeMapsUrl } from "@/lib/maps";
import { money } from "@/lib/money";
import type { TripState } from "@/lib/types";

export default function TripSummary({ trip }: { trip: TripState }) {
  const flight = trip.booked_flight;
  const hotel = trip.selected_hotel;
  // Agent 0 can capture several departure cities but Agent 1 only prices
  // one route, so say which legs are still outstanding rather than letting
  // the total read as if it covered the whole party.
  const unpriced = (trip.origins ?? []).filter((o) => o.city !== trip.origin);
  // Room rates are per night; the trip's cost is the stay.
  const nights = Math.max(
    1,
    Math.round(
      (new Date(trip.selected_date_window.end).getTime() -
        new Date(trip.selected_date_window.start).getTime()) /
        86_400_000
    )
  );

  return (
    <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow)]">
      <div>
        <p className="text-xs uppercase tracking-wide text-[var(--text-muted)]">Your trip</p>
        <h2 className="text-xl font-semibold">{trip.resolved_destination}</h2>
        <p className="text-sm text-[var(--text-muted)]">
          {trip.selected_date_window.start} → {trip.selected_date_window.end} ·{" "}
          {trip.travellers} traveller{trip.travellers > 1 ? "s" : ""}
        </p>
        {unpriced.length > 0 && (
          <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
            Flights below cover the {trip.origin} leg only —{" "}
            {unpriced.map((o) => `${o.travellers} from ${o.city}`).join(", ")} still to book.
          </p>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-[var(--surface-2)] p-3">
          <p className="text-xs uppercase tracking-wide text-[var(--text-muted)]">Flight</p>
          <p className="font-medium">{flight.carrier}</p>
          <p className="text-sm text-[var(--text-muted)]">
            {flight.origin} → {flight.destination} · {money(flight.price)}
          </p>
          <p className="mt-1 text-sm">
            Confirmation <span className="font-mono font-medium">{flight.confirmation}</span>
          </p>
        </div>

        <div className="rounded-xl bg-[var(--surface-2)] p-3">
          <p className="text-xs uppercase tracking-wide text-[var(--text-muted)]">Stay</p>
          <p className="font-medium">{hotel.name}</p>
          <p className="text-sm text-[var(--text-muted)]">
            {money(hotel.price * nights)} for {nights} night{nights === 1 ? "" : "s"}
            {hotel.rating !== null ? ` · ★ ${hotel.rating}` : ""}
          </p>
          <p className="text-xs text-[var(--text-muted)]">{money(hotel.price)} / night</p>
          <a
            href={hotel.booking_link}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-block text-sm font-medium text-[var(--accent)] underline underline-offset-2"
          >
            Finish booking →
          </a>
        </div>
      </div>

      <div>
        <p className="mb-2 text-xs uppercase tracking-wide text-[var(--text-muted)]">
          Day by day (route-optimised)
        </p>
        <div className="space-y-2">
          {trip.routed_itinerary.map((day) => (
            <div key={day.day} className="rounded-xl border border-[var(--border)] p-3">
              <p className="text-sm font-medium">
                Day {day.day}
                {day.title ? ` · ${day.title}` : ""}
              </p>
              <ol className="mt-1 space-y-0.5">
                {day.places.map((place, i) => (
                  <li key={place} className="text-sm text-[var(--text-muted)]">
                    <span className="text-[var(--accent)]">{i + 1}.</span>{" "}
                    <a
                      href={placeMapsUrl(place, trip.resolved_destination)}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={`See ${place} on Google Maps`}
                      className="underline decoration-transparent underline-offset-2 transition-colors hover:decoration-current"
                    >
                      {place}
                    </a>
                    {day.route_legs[i] && (
                      <span className="ml-1 text-xs">
                        ↓ {day.route_legs[i].duration_min} min {day.route_legs[i].mode}
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
