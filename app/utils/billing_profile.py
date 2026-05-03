"""
Verificare date minime pentru facturare (PF / PJ) — aliniat la coloanele din users / companies.
"""
from __future__ import annotations

from typing import Any

# (cheie_db, etichetă UI)
PF_USER_FIELDS: tuple[tuple[str, str], ...] = (
    ("invoice_full_name", "Numele complet pe factură"),
    ("invoice_street", "Adresă (stradă, nr.)"),
    ("invoice_city", "Localitate"),
    ("invoice_county", "Județ"),
    ("invoice_postal_code", "Cod poștal"),
    ("invoice_phone", "Telefon facturare"),
)

PJ_USER_FIELDS: tuple[tuple[str, str], ...] = (
    ("invoice_phone", "Telefon facturare"),
)

PJ_COMPANY_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "Denumire firmă"),
    ("cui", "CUI"),
    ("reg_com", "Nr. Registrul Comerțului"),
)


def _nonempty(row: dict[str, Any], key: str) -> bool:
    return bool(str(row.get(key) or "").strip())


def _company_has_invoice_address(company: dict[str, Any]) -> bool:
    if (
        _nonempty(company, "invoice_street")
        and _nonempty(company, "invoice_city")
        and _nonempty(company, "invoice_county")
        and _nonempty(company, "invoice_postal_code")
    ):
        return True
    return _nonempty(company, "address")


def billing_readiness(
    user: dict[str, Any],
    company: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Returnează:
      ok: bool
      customer_type: 'PF' | 'PJ' | None
      missing_user: [(key, label), ...]
      missing_company: [(key, label), ...]
    """
    ct = (user.get("invoice_customer_type") or "").strip().upper()
    missing_user: list[tuple[str, str]] = []
    missing_company: list[tuple[str, str]] = []

    if ct not in ("PF", "PJ"):
        missing_user.append(("invoice_customer_type", "Tip client (PF sau PJ)"))
        return {
            "ok": False,
            "customer_type": None,
            "missing_user": missing_user,
            "missing_company": missing_company,
        }

    if ct == "PF":
        for key, label in PF_USER_FIELDS:
            if not _nonempty(user, key):
                missing_user.append((key, label))
        return {
            "ok": len(missing_user) == 0,
            "customer_type": "PF",
            "missing_user": missing_user,
            "missing_company": missing_company,
        }

    cid = user.get("company_id")
    if not cid:
        missing_user.append(("company_id", "Firma asociată contului (selectează / creează firmă)"))
        return {
            "ok": False,
            "customer_type": "PJ",
            "missing_user": missing_user,
            "missing_company": missing_company,
        }

    co = company or {}
    for key, label in PJ_COMPANY_FIELDS:
        if not _nonempty(co, key):
            missing_company.append((key, label))
    if not _company_has_invoice_address(co):
        missing_company.append(
            (
                "invoice_address",
                "Adresă sediu (completă sau stradă + localitate + județ + CP)",
            )
        )
    for key, label in PJ_USER_FIELDS:
        if not _nonempty(user, key):
            missing_user.append((key, label))

    return {
        "ok": len(missing_user) == 0 and len(missing_company) == 0,
        "customer_type": "PJ",
        "missing_user": missing_user,
        "missing_company": missing_company,
    }


def clean_row_for_forms(row: dict[str, Any]) -> dict[str, Any]:
    """Pentru template-uri: NULL / string «None» nu apar ca text în input-uri."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if v is None:
            out[k] = ""
        elif isinstance(v, str) and v.strip() in ("None", "null", "NULL"):
            out[k] = ""
        else:
            out[k] = v
    return out


def safe_internal_path(next_url: str | None) -> str | None:
    """Doar path-uri relative interne (fără open redirect)."""
    if not next_url or not isinstance(next_url, str):
        return None
    n = next_url.strip()
    if not n.startswith("/") or n.startswith("//"):
        return None
    return n
