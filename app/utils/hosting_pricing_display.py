"""
Prețuri pagină hosting: TVA din SQLite (`vat_rates`), afișare tipic fără TVA + TVA adăugat.
"""
from __future__ import annotations

import os
from typing import Any, Literal

from app.utils.hosting_packages import (
    PACKAGE_EUR_CENTS,
    PACKAGE_LABELS_RO,
    hosting_amount_cents_ex_vat,
)
from app.utils.vat_db import get_active_vat_rate

VatDisplayMode = Literal["included", "excluded", "both"]


def _env_bool(name: str, default: bool) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def vat_display_mode() -> VatDisplayMode:
    """
    excluded — afișare recomandată: bază fără TVA + linie TVA + total cu TVA.
    included — doar total cu TVA (sumele sunt deja TTC în sursă).
    both — variantă compactă net + TVA = TTC.
    """
    m = (os.getenv("PRICING_VAT_DISPLAY") or "excluded").strip().lower()
    if m in ("included", "excluded", "both"):
        return m  # type: ignore[return-value]
    return "excluded"


def prices_stored_as_net() -> bool:
    """Centii din PACKAGE_EUR_CENTS sunt fără TVA (ex. 250 = 2,50 EUR bază)."""
    return _env_bool("PRICING_PRICES_STORED_AS_NET", True)


def domain_catalog_is_gross() -> bool:
    """Prețul din catalog Hostinger (centi) e tratat ca TTC → îl descompunem cu cota din DB."""
    return _env_bool("PRICING_DOMAIN_CATALOG_IS_GROSS", True)


async def build_hosting_pricing_context() -> dict[str, Any]:
    """Date JSON pentru hosting/index.html — `vat_rate` vine din tabelul `vat_rates`."""
    rate = await get_active_vat_rate("RO")
    mode = vat_display_mode()
    net_packages = prices_stored_as_net()
    gross_catalog = domain_catalog_is_gross()
    packages: list[dict[str, Any]] = []
    for key, cents in sorted(PACKAGE_EUR_CENTS.items(), key=lambda x: x[1]):
        packages.append(
            {
                "id": key,
                "label": PACKAGE_LABELS_RO.get(key, key),
                "eur_cents_monthly": cents,
                "eur_cents_yearly": hosting_amount_cents_ex_vat(key, "year"),
            }
        )
    return {
        "vat_rate": rate,
        "vat_display": mode,
        "prices_stored_as_net": net_packages,
        "domain_catalog_is_gross": gross_catalog,
        "currency": "EUR",
        "packages": packages,
        "footer_note": (os.getenv("PRICING_LEGAL_FOOTER") or "").strip()
        or (
            "Prețurile hosting din listă sunt fără TVA; TVA-ul este cel din baza de date (tabelul vat_rates), "
            "actualizabil la fiecare schimbare legislativă. Domeniul: estimare din catalog registrar; "
            "suma finală apare în Stripe / factură."
        ),
    }
