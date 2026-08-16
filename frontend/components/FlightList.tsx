"use client";

/**
 * Agent 1's flight options, with client-side sorting (price / duration /
 * departure time), since Duffel returns offers in its own order rather
 * than any of those.
 *
 * Sorting is deliberately client-side: the options are already fetched and
 * pinned in TripState, so re-sorting must not trigger a new search — a new
 * search would return different offer IDs than the ones being displayed
 * (see backend/app/agents/agent1_flights.py on replay safety).
 */
import { useMemo, useState } from "react";

import { money } from "@/lib/money";
import type { FlightOption } from "@/lib/types";

type SortKey = "price" | "duration_min" | "departing_at";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "price", label: "Cheapest" },
  { key: "duration_min", label: "Fastest" },
  { key: "departing_at", label: "Earliest" },
];

interface Props {
  flights: FlightOption[];
  budget: number;
  disabled?: boolean;
  onSelect: (id: string) => void;
}

function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

function formatTime(iso: string): string {
  // Duffel timestamps are local to each airport and carry no zone, so
  // slice the clock time out rather than letting Date shift it.
  return iso.slice(11, 16);
}

export default function FlightList({ flights, budget, disabled, onSelect }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("price");
  const [desc, setDesc] = useState(false);

  // Places like Tawang have no airport of their own, so the booking may
  // land in a different city. Say so up front rather than surprising them.
  const arrival = flights[0]?.destination_airport;
  const arrivalCity = flights[0]?.destination_city;

  const sorted = useMemo(() => {
    const copy = [...flights];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const cmp = typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv));
      return desc ? -cmp : cmp;
    });
    return copy;
  }, [flights, sortKey, desc]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {SORTS.map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => (s.key === sortKey ? setDesc((d) => !d) : (setSortKey(s.key), setDesc(false)))}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              s.key === sortKey
                ? "bg-[var(--accent)] text-[var(--accent-text)]"
                : "bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--text)]"
            }`}
          >
            {s.label}
            {s.key === sortKey ? (desc ? " ↓" : " ↑") : ""}
          </button>
        ))}
        <span className="ml-auto text-xs text-[var(--text-muted)]">
          budget for flights: {money(budget)}
        </span>
      </div>

      {arrival && (
        <p className="text-xs text-[var(--text-muted)]">
          Arriving into {arrival}
          {arrivalCity ? `, ${arrivalCity}` : ""}
        </p>
      )}

      <ul className="space-y-2">
        {sorted.map((f) => {
          const overBudget = f.price > budget;
          return (
            <li
              key={f.id}
              className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{f.carrier}</p>
                <p className="text-xs text-[var(--text-muted)]">
                  {f.origin} {formatTime(f.departing_at)} → {f.destination}{" "}
                  {formatTime(f.arriving_at)} · {formatDuration(f.duration_min)} ·{" "}
                  {f.stops === 0 ? "direct" : `${f.stops} stop${f.stops > 1 ? "s" : ""}`}
                </p>
                {/* The return leg, or an honest note that there isn't one:
                    a route with no round-trip inventory falls back to
                    one-way, and that has to be visible before booking. */}
                {f.has_return && f.return_departing_at ? (
                  <p className="text-xs text-[var(--text-muted)]">
                    back {f.destination} {formatTime(f.return_departing_at)} → {f.origin}{" "}
                    {f.return_arriving_at ? formatTime(f.return_arriving_at) : ""}
                    {f.return_stops === 0 ? " · direct" : ""}
                  </p>
                ) : (
                  <p className="text-xs text-amber-600 dark:text-amber-400">
                    one way — no return found for these dates
                  </p>
                )}
              </div>

              <div className="text-right">
                <p className="font-semibold">{money(f.price)}</p>
                <p className="text-[11px] text-[var(--text-muted)]">
                  total for the party
                  {/* Airlines quote in their own currency; the rupee figure
                      is converted (backend services/fx.py). Say when that
                      came from a fallback rate rather than a live one. */}
                  {f.fx_approximate ? " · approx. converted" : ""}
                </p>
                {overBudget && (
                  <p className="text-xs text-amber-600 dark:text-amber-400">over budget</p>
                )}
              </div>

              <button
                type="button"
                disabled={disabled}
                onClick={() => onSelect(f.id)}
                className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-[var(--accent-text)] transition-opacity disabled:opacity-40"
              >
                Book
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
