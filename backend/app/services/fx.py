"""
Currency conversion to INR.

Everything the user sees — budget, fares, room rates — is in one currency,
so the figures can actually be compared and subtracted. Before this, the
budget was rupees, Duffel quoted EUR and hotels came back in USD, and
`budget_remaining` subtracted all three from each other, which produced a
number that meant nothing.

Where a provider can quote INR itself we ask it to (SerpApi hotels does);
this module handles the ones that can't (Duffel prices in the airline's
own currency).

Rates come from open.er-api.com — free, no API key. They're cached for the
process lifetime: a mid-session rate change would make two prices on the
same screen inconsistent, and daily-ish accuracy is fine for planning.

If that endpoint is unreachable, `FALLBACK_RATES` keeps the pipeline
running for the handful of currencies airlines actually quote in. Those
figures are approximate and will drift, so anything converted through them
is flagged (`approximate=True`) rather than presented as exact. The
alternative — passing an unconverted foreign figure through — is the bug
this whole module exists to prevent, so a rough rupee beats an exact euro
that gets subtracted from a rupee budget.
"""
from typing import Dict, Optional, Tuple

import httpx

TARGET = "INR"
RATES_URL = "https://open.er-api.com/v6/latest/{base}"

# Rough INR-per-unit, used ONLY when the live rate endpoint is down.
# Deliberately a short list: these are what airlines actually quote in.
# Snapshot taken 2026-08-11 — they will drift, which is why anything
# converted through them is flagged approximate rather than shown as exact.
FALLBACK_RATES: Dict[str, float] = {
    "USD": 95.0,
    "EUR": 110.0,
    "GBP": 129.0,
    "AED": 26.0,
    "SGD": 74.0,
}

_cache: Dict[str, float] = {}


def rate_to_inr(currency: str) -> Tuple[Optional[float], bool]:
    """How many rupees one unit of `currency` is worth.

    Returns (rate, approximate). `approximate` is True when the live
    endpoint failed and FALLBACK_RATES supplied the figure, so callers can
    label the number instead of overstating its precision.
    """
    currency = (currency or "").upper()
    if not currency:
        return None, False
    if currency == TARGET:
        return 1.0, False
    if currency in _cache:
        return _cache[currency], False

    try:
        response = httpx.get(RATES_URL.format(base=currency), timeout=10)
        response.raise_for_status()
        rate = response.json().get("rates", {}).get(TARGET)
    except (httpx.HTTPError, ValueError):
        rate = None

    if rate:
        _cache[currency] = float(rate)
        return float(rate), False

    fallback = FALLBACK_RATES.get(currency)
    return (fallback, True) if fallback else (None, False)


def to_inr(amount: float, currency: str) -> Tuple[Optional[float], bool]:
    """Convert an amount to INR.

    Returns (rupees, approximate). Rupees is None only when the currency is
    unknown to both the live endpoint and FALLBACK_RATES — in which case
    the caller must DROP the priced item, not pass it through. Silently
    treating a foreign figure as rupees is exactly what this prevents.
    """
    rate, approximate = rate_to_inr(currency)
    if rate is None:
        return None, False
    return round(amount * rate), approximate
