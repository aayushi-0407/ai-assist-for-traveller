"use client";

/**
 * Optional override of the automatic flights-vs-hotel budget split, shown
 * just before searching (backend agent1_flights.ask_budget).
 *
 * "Optional" is the important part: the Budget Allocator already produced
 * a usable split, so the primary action is "looks good" — the inputs are
 * there for people who arrive with specific numbers in mind.
 */
import { useState } from "react";

interface Props {
  allocation: Record<string, number>;
  total: number;
  disabled?: boolean;
  onSubmit: (values: { flights: number | null; hotel: number | null }) => void;
}

export default function BudgetSplit({ allocation, total, disabled, onSubmit }: Props) {
  const [flights, setFlights] = useState(String(Math.round(allocation.flights)));
  const [hotel, setHotel] = useState(String(Math.round(allocation.hotel)));

  const flightsNum = Number(flights) || 0;
  const hotelNum = Number(hotel) || 0;
  const overspent = flightsNum + hotelNum > total;

  const changed =
    flightsNum !== Math.round(allocation.flights) || hotelNum !== Math.round(allocation.hotel);

  return (
    <div className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <p className="text-xs text-[var(--text-muted)]">
        Total budget {total.toLocaleString()} · the rest covers activities and a buffer
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        {[
          { label: "Flights", value: flights, set: setFlights },
          { label: "Hotel", value: hotel, set: setHotel },
        ].map((f) => (
          <label key={f.label} className="block">
            <span className="text-xs font-medium text-[var(--text-muted)]">{f.label}</span>
            <input
              type="number"
              min={0}
              value={f.value}
              disabled={disabled}
              onChange={(e) => f.set(e.target.value)}
              className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)] disabled:opacity-50"
            />
          </label>
        ))}
      </div>

      {overspent && (
        <p className="text-xs text-amber-600 dark:text-amber-400">
          That&apos;s more than your total budget — you can still go ahead, but there
          will be nothing left for activities.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => onSubmit({ flights: null, hotel: null })}
          className={`rounded-lg px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-40 ${
            changed
              ? "border border-[var(--border)]"
              : "bg-[var(--accent)] text-[var(--accent-text)]"
          }`}
        >
          Looks good
        </button>
        {changed && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onSubmit({ flights: flightsNum, hotel: hotelNum })}
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-text)] transition-opacity disabled:opacity-40"
          >
            Use these amounts
          </button>
        )}
        <span className="text-xs text-[var(--text-muted)]">or type it below</span>
      </div>
    </div>
  );
}
