/**
 * Money formatting. Every amount in this app is INR — the backend converts
 * provider quotes before they reach the pipeline (see
 * backend/app/services/fx.py), so nothing here has to handle a second
 * currency.
 *
 * Using the en-IN locale rather than the browser's own is deliberate on
 * both counts: it pins the ₹ symbol regardless of where the user is, and
 * it gives the Indian grouping a rupee figure is expected to have —
 * ₹1,20,000, not ₹120,000. A bare `toLocaleString()` produced neither.
 */

const RUPEES = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

/** e.g. 120000 -> "₹1,20,000". Nullish renders as an em dash, so a missing
 *  price never reads as free. */
export function money(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return "—";
  return RUPEES.format(amount);
}

/** Digits only, for inputs and tight columns where the symbol is already
 *  established by a nearby label. */
export function amount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value);
}
