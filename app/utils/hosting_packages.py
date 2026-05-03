"""
Pachete hosting — sursă unică pentru UI și Stripe.

- `PACKAGE_EUR_CENTS`: lunar, **centi EUR fără TVA** (dacă PRICING_PRICES_STORED_AS_NET=true în afișare).
- `PACKAGE_EUR_CENTS_YEARLY`: anual fără TVA; ofertă 11 plătite / 12 primite = **11 ×** preț lunar net pe tier. Dacă lipsește cheia, fallback 12 × lunar.
"""
from __future__ import annotations

PACKAGE_EUR_CENTS: dict[str, int] = {
    "starter": 300,
    "pro": 500,
    "business": 1000,
}

# Anual: 11 × lunar (net) — mesaj UI „plătești 11 luni, beneficiezi de 12”.
PACKAGE_EUR_CENTS_YEARLY: dict[str, int] = {
    "starter": 3300,
    "pro": 5500,
    "business": 11000,
}


def hosting_amount_cents_ex_vat(tier: str, interval: str) -> int:
    tid = tier.strip().lower()
    if tid not in PACKAGE_EUR_CENTS:
        raise ValueError("Pachet invalid")
    if (interval or "month").strip().lower() == "year":
        y = PACKAGE_EUR_CENTS_YEARLY.get(tid)
        if y is not None:
            return int(y)
        return int(PACKAGE_EUR_CENTS[tid]) * 12
    return int(PACKAGE_EUR_CENTS[tid])


PACKAGE_LABELS_RO: dict[str, str] = {
    "starter": "Starter",
    "pro": "WordPress Blog",
    "business": "WordPress Shop",
}
