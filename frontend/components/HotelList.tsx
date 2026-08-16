"use client";

/**
 * Agent 2's hotel options — photo, rating, review count, class and
 * amenities, so they can be compared at a glance, plus a link to the real
 * reviews on Google Maps.
 *
 * Picking one does NOT book it: Agent 2 is search + deep-link only (PRD
 * section 7), so the actual booking link is surfaced in the final summary.
 */
import { useMemo, useState } from "react";

import { money } from "@/lib/money";
import type { HotelOption } from "@/lib/types";

type SortKey = "price" | "rating";

interface Props {
  hotels: HotelOption[];
  budget: number;
  /** Length of the reconciled stay. Rates are per night but the budget is
   *  a whole-trip figure, so both are shown — a nightly rate on its own
   *  makes a long stay look affordable when it isn't. */
  nights: number;
  disabled?: boolean;
  onSelect: (id: string) => void;
}

export default function HotelList({ hotels, budget, nights, disabled, onSelect }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("price");

  const sorted = useMemo(() => {
    const copy = [...hotels];
    copy.sort((a, b) =>
      // Cheapest first, but best-rated first — ascending price vs
      // descending rating is what people actually expect from each.
      sortKey === "price" ? a.price - b.price : (b.rating ?? 0) - (a.rating ?? 0)
    );
    return copy;
  }, [hotels, sortKey]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {(["price", "rating"] as SortKey[]).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setSortKey(k)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              k === sortKey
                ? "bg-[var(--accent)] text-[var(--accent-text)]"
                : "bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--text)]"
            }`}
          >
            {k === "price" ? "Cheapest" : "Best rated"}
          </button>
        ))}
        <span className="ml-auto text-xs text-[var(--text-muted)]">
          budget for the stay: {money(budget)}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {sorted.map((h) => (
          <div
            key={h.id}
            className="flex flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]"
          >
            {h.image && (
              // eslint-disable-next-line @next/next/no-img-element -- Google CDN
              // URL straight from SerpApi; next/image would need the remote
              // host allow-listed for no benefit here.
              <img
                src={h.image}
                alt={h.name}
                loading="lazy"
                className="h-32 w-full bg-[var(--surface-2)] object-cover"
              />
            )}

            <div className="flex flex-1 flex-col p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="min-w-0 flex-1 font-medium leading-snug">{h.name}</p>
                {h.rating !== null && (
                  <span className="shrink-0 rounded-full bg-[var(--surface-2)] px-2 py-0.5 text-xs font-medium">
                    ★ {h.rating}
                  </span>
                )}
              </div>

              <p className="mt-1 text-xs text-[var(--text-muted)]">
                {h.hotel_class ?? "Hotel"}
                {h.review_count ? ` · ${h.review_count.toLocaleString()} reviews` : ""}
                {h.location_rating ? ` · location ${h.location_rating}` : ""}
              </p>

              {h.amenities.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {h.amenities.map((a) => (
                    <span
                      key={a}
                      className="rounded bg-[var(--surface-2)] px-1.5 py-0.5 text-[11px] text-[var(--text-muted)]"
                    >
                      {a}
                    </span>
                  ))}
                </div>
              )}

              <p className="mt-2 text-sm font-semibold">
                {money(h.price * nights)}
                <span className="ml-1 text-xs font-normal text-[var(--text-muted)]">
                  for {nights} night{nights === 1 ? "" : "s"}
                </span>
              </p>
              <p className="text-xs text-[var(--text-muted)]">{money(h.price)} / night</p>

              <div className="mt-auto flex items-center gap-2 pt-3">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onSelect(h.id)}
                  className="flex-1 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-[var(--accent-text)] transition-opacity disabled:opacity-40"
                >
                  Choose
                </button>
                <a
                  href={h.reviews_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--text-muted)] hover:text-[var(--text)]"
                >
                  Reviews →
                </a>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
