"use client";

/**
 * Agent 3's compare step — full day-by-day plans for each shortlisted
 * destination, side by side. This is the screen where the destination
 * actually gets decided, so each column ends with its own "choose" button.
 *
 * Each column also carries what the parallel availability branch found for
 * that destination: the dates flights AND hotels both actually have, and
 * what the trip costs there. That's the point of running Agents 1, 2 and 3
 * together — the choice is made on real prices and bookable dates rather
 * than on a plan whose cost only emerges two steps later.
 *
 * A destination with no workable window is still shown (its itinerary is
 * real and worth reading) but can't be chosen, and says which half was
 * missing so the user knows what to change.
 *
 * On narrow screens the columns stack; on wide ones they scroll
 * horizontally rather than squeezing, so a day's places stay readable.
 */
import { placeMapsUrl } from "@/lib/maps";
import { money } from "@/lib/money";
import type { DayPlan, DestinationAvailability } from "@/lib/types";

interface Props {
  itineraries: Record<string, DayPlan[]>;
  dateWindow: { start: string; end: string };
  availability: Record<string, DestinationAvailability>;
  bookable: string[];
  disabled?: boolean;
  onChoose: (destination: string) => void;
}

function totalCost(days: DayPlan[]): number {
  return days.reduce((sum, d) => sum + (d.est_cost ?? 0), 0);
}

const BLOCKED_REASON: Record<string, string> = {
  hotels: "Flights available, but nowhere to stay",
  flights: "Rooms available, but no flights",
  both: "No flights or rooms found",
  error: "Couldn't check this one",
};

/** e.g. "Jul 29 → Aug 5" — the full ISO dates are too heavy for a column
 *  header, and the year is already implied by the trip window. */
function shortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function ItineraryCompare({
  itineraries,
  dateWindow,
  availability,
  bookable,
  disabled,
  onChoose,
}: Props) {
  const names = Object.keys(itineraries);
  const anyShifted = names.some((n) => availability[n]?.shifted_by);

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--text-muted)]">
        Around {dateWindow.start} → {dateWindow.end}
        {anyShifted &&
          " · some dates moved to where flights and rooms were both available"}
      </p>

      <div className="-mx-1 overflow-x-auto px-1 pb-1">
        <div
          className="grid gap-3"
          style={{ gridTemplateColumns: `repeat(${names.length}, minmax(15rem, 1fr))` }}
        >
          {names.map((name) => {
            const days = itineraries[name];
            const a = availability[name];
            const canBook = bookable.includes(name);
            return (
              <div
                key={name}
                className={`flex flex-col rounded-xl border bg-[var(--surface)] p-4 ${
                  canBook ? "border-[var(--border)]" : "border-dashed border-[var(--border)]"
                }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <h3 className="font-semibold">{name}</h3>
                  <span className="text-xs text-[var(--text-muted)]">
                    activities ~{money(totalCost(days))}
                  </span>
                </div>

                {/* What the availability branch found for this destination:
                    real dates, real total, and whether it fits. */}
                {a && canBook && (
                  <div className="mt-2 space-y-1.5 rounded-lg bg-[var(--surface-2)] p-2.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-xs font-medium">
                        {shortDate(a.window.start)} → {shortDate(a.window.end)}
                      </span>
                      {!!a.shifted_by && (
                        <span className="text-[11px] text-[var(--text-muted)]">
                          moved {a.shifted_by > 0 ? "+" : ""}
                          {a.shifted_by}d
                        </span>
                      )}
                    </div>
                    <div className="flex items-baseline justify-between gap-2 text-xs text-[var(--text-muted)]">
                      <span>Flights</span>
                      <span className="tabular-nums">{money(a.cheapest_flight)}</span>
                    </div>
                    <div className="flex items-baseline justify-between gap-2 text-xs text-[var(--text-muted)]">
                      <span>
                        Hotel · {a.nights} night{a.nights === 1 ? "" : "s"}
                      </span>
                      <span className="tabular-nums">{money(a.hotel_total)}</span>
                    </div>
                    <div
                      className={`flex items-baseline justify-between gap-2 border-t border-[var(--border)] pt-1.5 text-xs font-semibold ${
                        a.fits_budget ? "" : "text-amber-600 dark:text-amber-400"
                      }`}
                    >
                      <span>{a.fits_budget ? "Total" : "Total · over budget"}</span>
                      <span className="tabular-nums">{money(a.trip_total)}</span>
                    </div>
                  </div>
                )}

                {a && !canBook && (
                  <div className="mt-2 rounded-lg bg-[var(--surface-2)] p-2.5">
                    <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
                      {BLOCKED_REASON[a.blocked_by ?? "both"] ?? "Not bookable"}
                    </p>
                    <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                      {a.windows_tried.length > 1
                        ? `Tried ${a.windows_tried.length} different weeks.`
                        : `Looked at ${shortDate(a.window.start)} → ${shortDate(a.window.end)}.`}
                    </p>
                  </div>
                )}

                <ol className="mt-3 flex-1 space-y-3">
                  {days.map((d) => (
                    <li key={d.day}>
                      <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
                        Day {d.day}
                        {d.title ? ` · ${d.title}` : ""}
                      </p>
                      <ul className="mt-1 space-y-0.5">
                        {d.places.map((p) => (
                          <li key={p} className="text-sm">
                            <span className="text-[var(--accent)]">•</span>{" "}
                            <a
                              href={placeMapsUrl(p, name)}
                              target="_blank"
                              rel="noopener noreferrer"
                              title={`See ${p} on Google Maps`}
                              className="underline decoration-transparent underline-offset-2 transition-colors hover:decoration-[var(--accent)]"
                            >
                              {p}
                            </a>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ol>

                <button
                  type="button"
                  disabled={disabled || !canBook}
                  title={canBook ? undefined : "Nothing bookable for these dates"}
                  onClick={() => onChoose(name)}
                  className="mt-4 w-full rounded-lg bg-[var(--accent)] px-3 py-2 text-sm font-medium text-[var(--accent-text)] transition-opacity disabled:opacity-40"
                >
                  {canBook ? `Go with ${name}` : "Not available"}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
