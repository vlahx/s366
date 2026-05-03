"""
Cote TVA (RO) din SQLite — istoric pe `effective_from`, ca la schimbare legislativă
să rămână trasabilitate și să se poată folosi cota corectă la o dată.
"""
from __future__ import annotations

import os

from app.models.sqlite_model import fetch_one


def _env_fallback_rate() -> float:
    raw = (os.getenv("PRICING_VAT_RATE") or "0.19").strip().replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return 0.19


async def get_active_vat_rate(country_code: str = "RO") -> float:
    """
    Cota activă pentru țară: ultima înregistrare cu effective_from <= azi (UTC, date SQLite).
    Dacă nu există rânduri, folosește PRICING_VAT_RATE din mediu (implicit 0.19).
    """
    cc = (country_code or "RO").strip().upper() or "RO"
    row = await fetch_one(
        """
        SELECT rate FROM vat_rates
        WHERE UPPER(country_code) = ?
          AND date(effective_from) <= date('now')
        ORDER BY date(effective_from) DESC, id DESC
        LIMIT 1
        """,
        (cc,),
    )
    if row is None:
        return _env_fallback_rate()
    try:
        return float(row["rate"] if hasattr(row, "keys") else row[0])
    except (TypeError, ValueError, KeyError, IndexError):
        return _env_fallback_rate()
