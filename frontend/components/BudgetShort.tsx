"use client";

/**
 * Shown when nothing was available within the budget set aside for
 * flights or the hotel (backend agent1_flights.raise_budget /
 * agent2_hotels.raise_budget).
 *
 * Deliberately states the cheapest real price and pre-fills it, so the
 * user can see exactly how short they are and accept in one click. The
 * graph then re-filters the already-searched options against the new
 * figure (it does not re-search — see backend agent1_flights.raise_budget).
 */
import { useState } from "react";

import { money } from "@/lib/money";

interface Props {
  allocated: number;
  cheapest: number;
  suggested: number;
  disabled?: boolean;
  onSubmit: (amount: number) => void;
}

export default function BudgetShort({
  allocated,
  cheapest,
  suggested,
  disabled,
  onSubmit,
}: Props) {
  const [amount, setAmount] = useState(String(Math.ceil(suggested)));
  const value = Number(amount) || 0;
  const stillShort = value < cheapest;

  return (
    <div className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-900/60 dark:bg-amber-950/30">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
        <span className="text-[var(--text-muted)]">
          Your budget: <strong className="text-[var(--text)]">{money(allocated)}</strong>
        </span>
        <span className="text-[var(--text-muted)]">
          Cheapest available: <strong className="text-[var(--text)]">{money(cheapest)}</strong>
        </span>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="flex-1">
          <span className="text-xs font-medium text-[var(--text-muted)]">New budget</span>
          <input
            type="number"
            min={0}
            value={amount}
            disabled={disabled}
            onChange={(e) => setAmount(e.target.value)}
            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)] disabled:opacity-50"
          />
        </label>
        <button
          type="button"
          disabled={disabled || value <= 0}
          onClick={() => onSubmit(value)}
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-text)] transition-opacity disabled:opacity-40"
        >
          Search again
        </button>
      </div>

      {stillShort && (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          That&apos;s still below the cheapest option — you&apos;ll likely get no results again.
        </p>
      )}
    </div>
  );
}
