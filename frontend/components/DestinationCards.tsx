"use client";

/**
 * Agent 0's research output: candidate destinations with a photo, rating,
 * why-this-place and the best window to visit. Multi-select, because the
 * whole point of the next stage is comparing itineraries side by side
 * (PRD section 7).
 *
 * The card body is a button (select/deselect); the "View on Maps" link is
 * NOT nested inside it — a real <a> inside a <button> is invalid HTML and
 * clicking it would also toggle selection. It sits as a sibling instead.
 */
import { useState } from "react";

import { photoUrl } from "@/lib/api";
import type { Candidate } from "@/lib/types";

interface Props {
  candidates: Candidate[];
  /** Slots the user committed to at intake. Present only in fixed-date
   *  mode, where every card shares the same window rather than carrying
   *  its own seasonally-best one. */
  fixedWindows?: { start: string; end: string; label?: string }[];
  disabled?: boolean;
  onConfirm: (names: string[]) => void;
}

export default function DestinationCards({
  candidates,
  fixedWindows,
  disabled,
  onConfirm,
}: Props) {
  const [picked, setPicked] = useState<string[]>([]);

  function toggle(name: string) {
    setPicked((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );
  }

  return (
    <div className="space-y-3">
      {fixedWindows && fixedWindows.length > 0 && (
        <p className="text-xs text-[var(--text-muted)]">
          Timed to your dates:{" "}
          <span className="font-medium text-[var(--text)]">
            {fixedWindows.map((w) => w.label ?? `${w.start} → ${w.end}`).join(" or ")}
          </span>
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {candidates.map((c) => {
          const isPicked = picked.includes(c.name);
          return (
            <div
              key={c.name}
              className={`overflow-hidden rounded-xl border transition-all ${
                isPicked
                  ? "border-[var(--accent)] ring-1 ring-[var(--accent)]"
                  : "border-[var(--border)] hover:shadow-[var(--shadow)]"
              }`}
            >
              <button
                type="button"
                disabled={disabled}
                onClick={() => toggle(c.name)}
                className="block w-full bg-[var(--surface)] text-left disabled:opacity-60"
              >
                {c.photo_ref && (
                  // eslint-disable-next-line @next/next/no-img-element -- proxied
                  // through our own /photo route, so next/image's optimizer
                  // (which would need the remote host allow-listed) adds nothing.
                  <img
                    src={photoUrl(c.photo_ref, 640)}
                    alt={c.name}
                    loading="lazy"
                    className="h-32 w-full bg-[var(--surface-2)] object-cover"
                  />
                )}

                <div className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold">{c.name}</h3>
                    <span
                      className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[11px] ${
                        isPicked
                          ? "border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-text)]"
                          : "border-[var(--border)]"
                      }`}
                    >
                      {isPicked ? "✓" : ""}
                    </span>
                  </div>

                  <p className="mt-1.5 text-sm text-[var(--text-muted)]">{c.why}</p>

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-xs font-medium">
                      🗓 {c.window}
                    </span>
                    {c.rating !== null && (
                      <span className="rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-xs font-medium">
                        ★ {c.rating}
                        {c.review_count ? ` (${c.review_count.toLocaleString()})` : ""}
                      </span>
                    )}
                  </div>

                  {c.season_note && (
                    <p className="mt-2 text-xs italic text-[var(--text-muted)]">
                      {c.season_note}
                    </p>
                  )}
                </div>
              </button>

              {c.maps_url && (
                <div className="border-t border-[var(--border)] bg-[var(--surface)] px-4 py-2">
                  <a
                    href={c.maps_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-medium text-[var(--accent)] hover:underline"
                  >
                    View photos & reviews on Google Maps →
                  </a>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={disabled || picked.length === 0}
          onClick={() => onConfirm(picked)}
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-text)] transition-opacity disabled:opacity-40"
        >
          {picked.length > 1 ? `Compare ${picked.length} itineraries` : "Build itinerary"}
        </button>
        <span className="text-xs text-[var(--text-muted)]">
          or just type your answer below
        </span>
      </div>
    </div>
  );
}
