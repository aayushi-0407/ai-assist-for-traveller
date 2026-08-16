"use client";

/**
 * Agent 0's criteria intake — the one form shown before any research runs
 * (backend agent0_best_time.collect).
 *
 * It covers the four things a trip can't be planned without: where they
 * want to go, where they're setting off from, when they can travel, and
 * what they'll spend. Two of those are plural by nature — a group can
 * converge from several cities, and dates can be a fixed slot or a whole
 * month to place the trip inside — so those sections expand rather than
 * forcing a single value.
 *
 * Everything arrives prefilled from the opening message, so the normal
 * interaction is a glance and a confirm. `missing` marks the fields the
 * backend genuinely can't proceed without; those get flagged inline
 * instead of the form silently submitting something unusable.
 *
 * The budget split is the one question here that isn't just data capture:
 * how someone divides hotel vs. activities is what tells the researcher
 * whether they want somewhere to unwind or somewhere with plenty to do,
 * so the form names that inference out loud rather than hiding it.
 */
import { useState } from "react";

import { money } from "@/lib/money";
import type {
  BudgetSplitPref,
  DateMode,
  IntakeCriteria,
  IntakeSelection,
  OriginGroup,
  PartyType,
} from "@/lib/types";

interface Props {
  criteria: IntakeCriteria;
  /** Backend intake.REQUIRED — the node will not exit without these, so
   *  the submit button stays disabled until they're filled. */
  missing: string[];
  /** Backend intake.EXPECTED — chased, but conceded to a default if the
   *  user can't answer. Nudged, never blocking. */
  expected: string[];
  partyTypes: PartyType[];
  defaultSplit: BudgetSplitPref;
  disabled?: boolean;
  onSubmit: (values: IntakeSelection) => void;
}

const PARTY_LABELS: Record<PartyType, string> = {
  individual: "Just me",
  family: "Family",
  group: "Group of friends",
};

const SPLIT_LABELS: Record<keyof BudgetSplitPref, string> = {
  travel: "Travel",
  hotel: "Hotel",
  activities: "Activities",
};

/** Mirrors budget.style_from_preference on the backend — same margin, so
 *  the hint shown here is the intent research will actually receive. */
function styleHint(split: BudgetSplitPref): string {
  const total = split.travel + split.hotel + split.activities || 1;
  const hotel = split.hotel / total;
  const activities = split.activities / total;

  if (activities - hotel >= 0.1)
    return "Reads as an activity-led trip — I'll favour places with plenty going on.";
  if (hotel - activities >= 0.1)
    return "Reads as a relaxation trip — I'll favour places worth slowing down in.";
  return "Reads as a balanced trip — a bit of both.";
}

export default function IntakeForm({
  criteria,
  missing,
  expected,
  partyTypes,
  defaultSplit,
  disabled,
  onSubmit,
}: Props) {
  const prefilled = criteria.origins.length > 0 ? criteria.origins : [];

  const [destination, setDestination] = useState(criteria.destination_query ?? "");
  const [party, setParty] = useState<PartyType>(criteria.party_type ?? "individual");
  const [travellers, setTravellers] = useState(String(criteria.travellers ?? 1));
  // `separate` drives whether origins is a single city or a list of them.
  // Derived from the prefill, since two cities already in hand answers it.
  const [separate, setSeparate] = useState(prefilled.length > 1);
  const [origins, setOrigins] = useState<{ city: string; travellers: string }[]>(
    prefilled.length > 0
      ? prefilled.map((o) => ({ city: o.city, travellers: String(o.travellers) }))
      : [{ city: "", travellers: String(criteria.travellers ?? 1) }]
  );
  const [dateMode, setDateMode] = useState<DateMode>(criteria.date_mode ?? "flexible");
  const [dateQuery, setDateQuery] = useState(criteria.date_query ?? "");
  const [tripDays, setTripDays] = useState(
    criteria.trip_days ? String(criteria.trip_days) : ""
  );
  const [budget, setBudget] = useState(
    criteria.budget_total ? String(criteria.budget_total) : ""
  );
  const [split, setSplit] = useState<BudgetSplitPref>(
    criteria.budget_split_pref ?? defaultSplit
  );
  // Only send a split if they actually moved it. An untouched default must
  // stay untouched, or Agent 1 skips its own budget question believing the
  // user already made this call (see agent1_flights.ask_budget).
  const [splitTouched, setSplitTouched] = useState(criteria.budget_split_pref !== null);

  const headcount = Number(travellers) || 1;
  const activeOrigins = separate ? origins : origins.slice(0, 1);
  const filledOrigins = activeOrigins.filter((o) => o.city.trim());
  const budgetNum = Number(budget) || 0;

  // A gap the backend named AND that's still empty in the form. Re-checking
  // the value matters: the user may have just filled it in without submitting
  // yet, and a flag that stays lit after you've answered it reads as broken.
  const gap = (field: string, empty: boolean) =>
    (missing.includes(field) || expected.includes(field)) && empty;

  const needsDestination = gap("destination_query", !destination.trim());
  const needsOrigin = gap("origins", filledOrigins.length === 0);
  const needsBudget = gap("budget_total", budgetNum <= 0);
  const needsDates = gap("date_query", !dateQuery.trim());

  // Mirrors intake.REQUIRED — the three the node has no fallback for and
  // will keep re-asking about, so there's no point letting the form submit
  // without them. The soft ones (dates, trip length, split) don't gate:
  // the backend concedes those to a default rather than holding the
  // pipeline open on a question the user may not be able to answer.
  const ready = !!destination.trim() && filledOrigins.length > 0 && budgetNum > 0;

  // Percentages are shown normalised so the three always read as a whole,
  // however the raw numbers were entered. The backend rescales identically.
  const splitTotal = split.travel + split.hotel + split.activities || 1;
  const pct = (v: number) => Math.round((v / splitTotal) * 100);

  function setOriginField(i: number, field: "city" | "travellers", value: string) {
    setOrigins((prev) =>
      prev.map((o, idx) => (idx === i ? { ...o, [field]: value } : o))
    );
  }

  function submit() {
    const payload: OriginGroup[] = filledOrigins.map((o) => ({
      city: o.city.trim(),
      travellers: Math.max(1, Number(o.travellers) || 1),
    }));

    onSubmit({
      destination_query: destination.trim() || null,
      party_type: party,
      travellers: headcount,
      origins: payload,
      date_mode: dateMode,
      date_query: dateQuery.trim() || null,
      trip_days: Number(tripDays) || null,
      budget_total: budgetNum || null,
      // Sent as whole percentages; the backend normalises them to fractions.
      budget_split_pref: splitTouched
        ? { travel: pct(split.travel), hotel: pct(split.hotel), activities: pct(split.activities) }
        : defaultSplit,
    });
  }

  const fieldClass =
    "w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)] disabled:opacity-50";

  return (
    <div className="space-y-5 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      {/* --- 1. Destination brief ---------------------------------------- */}
      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
          Where to
        </h4>
        <input
          type="text"
          value={destination}
          disabled={disabled}
          placeholder="A hill station, somewhere with cherry blossoms, or a specific city"
          onChange={(e) => setDestination(e.target.value)}
          className={fieldClass}
        />
        {needsDestination ? (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            Even something vague works — it&apos;s the shortlist I build from.
          </p>
        ) : (
          <p className="text-xs text-[var(--text-muted)]">
            Vague is fine. I&apos;ll turn it into a shortlist of real places, and
            you pick as many as you want to compare.
          </p>
        )}
      </section>

      {/* --- 2. Who's going ---------------------------------------------- */}
      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
          Who&apos;s travelling
        </h4>
        <div className="flex flex-wrap items-center gap-2">
          {partyTypes.map((t) => (
            <button
              key={t}
              type="button"
              disabled={disabled}
              onClick={() => {
                setParty(t);
                if (t === "individual") setTravellers("1");
              }}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 ${
                party === t
                  ? "border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-text)]"
                  : "border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]"
              }`}
            >
              {PARTY_LABELS[t] ?? t}
            </button>
          ))}
          {party !== "individual" && (
            <label className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
              how many?
              <input
                type="number"
                min={2}
                value={travellers}
                disabled={disabled}
                onChange={(e) => setTravellers(e.target.value)}
                className="w-16 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 text-sm outline-none focus:border-[var(--accent)] disabled:opacity-50"
              />
            </label>
          )}
        </div>
      </section>

      {/* --- 3. Source(s) ----------------------------------------------- */}
      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
          Setting off from
        </h4>

        {party !== "individual" && (
          <div className="flex flex-wrap gap-2">
            {[
              { label: "All from the same place", value: false },
              { label: "From different places", value: true },
            ].map((opt) => (
              <button
                key={opt.label}
                type="button"
                disabled={disabled}
                onClick={() => {
                  setSeparate(opt.value);
                  // Opening the multi-origin case with a single blank row
                  // to fill is clearer than an empty section.
                  if (opt.value && origins.length === 1) {
                    setOrigins((prev) => [...prev, { city: "", travellers: "1" }]);
                  }
                }}
                className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 ${
                  separate === opt.value
                    ? "border-[var(--accent)] text-[var(--accent)]"
                    : "border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}

        <div className="space-y-2">
          {activeOrigins.map((o, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="text"
                value={o.city}
                disabled={disabled}
                placeholder="City you're flying from"
                onChange={(e) => setOriginField(i, "city", e.target.value)}
                className={fieldClass}
              />
              {separate && (
                <>
                  <input
                    type="number"
                    min={1}
                    value={o.travellers}
                    disabled={disabled}
                    aria-label="travellers from this city"
                    onChange={(e) => setOriginField(i, "travellers", e.target.value)}
                    className="w-16 shrink-0 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-2 py-2 text-sm outline-none focus:border-[var(--accent)] disabled:opacity-50"
                  />
                  {origins.length > 1 && (
                    <button
                      type="button"
                      disabled={disabled}
                      aria-label="remove this departure city"
                      onClick={() => setOrigins((prev) => prev.filter((_, idx) => idx !== i))}
                      className="shrink-0 px-1 text-sm text-[var(--text-muted)] hover:text-[var(--text)] disabled:opacity-40"
                    >
                      ✕
                    </button>
                  )}
                </>
              )}
            </div>
          ))}

          {separate && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => setOrigins((prev) => [...prev, { city: "", travellers: "1" }])}
              className="text-xs font-medium text-[var(--accent)] hover:underline disabled:opacity-40"
            >
              + another departure city
            </button>
          )}
        </div>

        {needsOrigin && (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            I need at least one departure city to check anything is reachable.
          </p>
        )}
      </section>

      {/* --- 4. Travel window -------------------------------------------- */}
      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
          When
        </h4>
        <div className="flex flex-wrap gap-2">
          {[
            { label: "Fixed dates", value: "fixed" as const },
            { label: "A flexible window", value: "flexible" as const },
          ].map((opt) => (
            <button
              key={opt.value}
              type="button"
              disabled={disabled}
              onClick={() => setDateMode(opt.value)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 ${
                dateMode === opt.value
                  ? "border-[var(--accent)] text-[var(--accent)]"
                  : "border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={dateQuery}
            disabled={disabled}
            placeholder={
              dateMode === "fixed"
                ? "e.g. 12–19 October (or two slots, if you have options)"
                : "e.g. sometime in March, or anytime Oct–Dec"
            }
            onChange={(e) => setDateQuery(e.target.value)}
            className={fieldClass}
          />
          <label className="flex shrink-0 items-center gap-2 text-xs text-[var(--text-muted)]">
            <input
              type="number"
              min={1}
              value={tripDays}
              disabled={disabled}
              placeholder="7"
              onChange={(e) => setTripDays(e.target.value)}
              className="w-16 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-2 py-2 text-sm outline-none focus:border-[var(--accent)] disabled:opacity-50"
            />
            days
          </label>
        </div>
        <p className="text-xs text-[var(--text-muted)]">
          {needsDates
            ? "Leave it blank if you're not sure and I'll pick the best season myself."
            : dateMode === "fixed"
              ? "I'll price exactly these dates and tell you honestly what each place is like then."
              : "I'll pick the best window inside that for each place I suggest — they'll differ."}
        </p>
      </section>

      {/* --- 5. Budget and how it divides -------------------------------- */}
      <section className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
          Budget
        </h4>
        {/* The ₹ sits in the field rather than in the placeholder so it
            stays visible once a number is typed — every figure in this app
            is rupees and the input is where that gets established. */}
        <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 focus-within:border-[var(--accent)]">
          <span className="text-sm text-[var(--text-muted)]">₹</span>
          <input
            type="number"
            min={0}
            value={budget}
            disabled={disabled}
            placeholder="Total for the whole trip"
            onChange={(e) => setBudget(e.target.value)}
            className="w-full bg-transparent py-2 text-sm outline-none disabled:opacity-50"
          />
        </div>
        {needsBudget && (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            Every suggestion is a guess without a figure to plan against.
          </p>
        )}

        <div className="space-y-2">
          {(Object.keys(SPLIT_LABELS) as (keyof BudgetSplitPref)[]).map((bucket) => (
            <label key={bucket} className="flex items-center gap-3">
              <span className="w-20 shrink-0 text-xs text-[var(--text-muted)]">
                {SPLIT_LABELS[bucket]}
              </span>
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={split[bucket]}
                disabled={disabled}
                onChange={(e) => {
                  setSplitTouched(true);
                  setSplit((prev) => ({ ...prev, [bucket]: Number(e.target.value) }));
                }}
                className="h-1 flex-1 accent-[var(--accent)] disabled:opacity-50"
              />
              <span className="w-24 shrink-0 text-right text-xs tabular-nums text-[var(--text-muted)]">
                {pct(split[bucket])}%
                {budgetNum > 0 && (
                  <span className="ml-1 opacity-70">
                    · {money(Math.round((budgetNum * pct(split[bucket])) / 100))}
                  </span>
                )}
              </span>
            </label>
          ))}
        </div>

        <p className="text-xs italic text-[var(--text-muted)]">{styleHint(split)}</p>
      </section>

      <div className="flex flex-wrap items-center gap-3 border-t border-[var(--border)] pt-3">
        <button
          type="button"
          disabled={disabled || !ready}
          onClick={submit}
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-text)] transition-opacity disabled:opacity-40"
        >
          Find me somewhere to go
        </button>
        <span className="text-xs text-[var(--text-muted)]">
          or just tell me below and I&apos;ll fill this in
        </span>
      </div>
    </div>
  );
}
