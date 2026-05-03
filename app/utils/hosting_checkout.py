"""
Stripe Checkout pentru hosting (abonament) + opțional înregistrare domeniu (plată unică, prima factură).

Recomandare Stripe (subscription mode):
  - un `line_items` cu preț **recurring** (lunar sau anual) pentru hosting;
  - al doilea `line_items` cu **price_data fără recurring** = plată unică pe prima factură
    (înregistrare domeniu 1 an). Documentație: line_items one-time apar doar pe factura inițială.

Alternativă simplă: totul anual (un singur recurring „year”) și includeți domeniul în preț / metadata
  — mai puțin flexibil, dar un singur flux de reînnoire.

Domeniu vs hosting: nu e nevoie de două sesiuni separate dacă folosiți combinația de mai sus.

Variabile utile:
  STRIPE_SECRET_KEY — obligatoriu
  STRIPE_PRICE_ID_<TIER> — dacă e setat, se folosește doar pentru `hosting_billing_interval=month`
  STRIPE_CHECKOUT_DOMAIN_LINE_ITEM — implicit true: adaugă linia one-time când `domain_registration_eur_cents` > 0 (setat server-side din catalog). Pune false ca să dezactivezi.
  STRIPE_CHARGE_VAT_ON_TOP — true: sumele din PACKAGE_* (fără TVA) se înmulțesc cu (1 + cotă TVA din DB) la checkout
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import stripe
from starlette.concurrency import run_in_threadpool

from app.models.sqlite_model import execute_insert, fetch_one
from app.utils.hosting_packages import PACKAGE_EUR_CENTS, hosting_amount_cents_ex_vat
from app.utils.vat_db import get_active_vat_rate

log = logging.getLogger(__name__)


def _stripe_secret() -> str:
    key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY lipsește din mediu")
    return key


def _env_bool(name: str, default: bool) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def public_base_url(request_base_url: str | None) -> str:
    env = os.getenv("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if env:
        return env
    if request_base_url:
        return str(request_base_url).rstrip("/")
    return "https://s366.online"


def _line_items_hosting(
    package_tier: str,
    *,
    interval: str,
    unit_amount_cents: int,
    allow_dashboard_price_id: bool,
) -> list[dict[str, Any]]:
    tid = package_tier.lower()
    env_key = f"STRIPE_PRICE_ID_{tid.upper()}"
    price_id = os.getenv(env_key, "").strip()
    if allow_dashboard_price_id and price_id and interval == "month":
        return [{"price": price_id, "quantity": 1}]
    if tid not in PACKAGE_EUR_CENTS:
        raise ValueError("Pachet invalid")
    inv = "year" if interval == "year" else "month"
    return [
        {
            "price_data": {
                "currency": "eur",
                "product_data": {"name": f"S366 AI Hosting — {tid} ({inv})"},
                "recurring": {"interval": inv},
                "unit_amount": int(unit_amount_cents),
            },
            "quantity": 1,
        }
    ]


def _line_item_domain_one_time(domain: str, unit_amount_cents: int) -> dict[str, Any]:
    return {
        "price_data": {
            "currency": "eur",
            "product_data": {"name": f"Înregistrare domeniu (1 an) — {domain}"},
            "unit_amount": int(unit_amount_cents),
        },
        "quantity": 1,
    }


async def create_hosting_checkout_session(
    *,
    domain: str,
    package_tier: str,
    user_id: int | None,
    request_base_url: str | None,
    hosting_billing_interval: str = "month",
    domain_registration_eur_cents: int | None = None,
) -> stripe.checkout.Session:
    dom = domain.strip().lower().rstrip(".")
    pkg = package_tier.strip().lower()
    interval = (hosting_billing_interval or "month").strip().lower()
    if interval not in ("month", "year"):
        interval = "month"
    if not dom or "." not in dom:
        raise ValueError("Domeniu invalid")
    if pkg not in PACKAGE_EUR_CENTS and not os.getenv(
        f"STRIPE_PRICE_ID_{pkg.upper()}", ""
    ).strip():
        raise ValueError("Pachet invalid")

    stripe.api_key = _stripe_secret()
    base = public_base_url(request_base_url)
    success_url = f"{base}/hosting/checkout/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/hosting/checkout/cancel"

    meta: dict[str, str] = {
        "domain": dom,
        "package_tier": pkg,
        "hosting_billing_interval": interval,
    }
    if user_id is not None:
        meta["user_id"] = str(user_id)

    base_hosting_cents = hosting_amount_cents_ex_vat(pkg, interval)
    vat_rate = await get_active_vat_rate("RO")
    vat_top_hosting = _env_bool("STRIPE_CHARGE_VAT_ON_TOP", False)
    if vat_top_hosting:
        hosting_charge_cents = int(round(base_hosting_cents * (1.0 + float(vat_rate))))
    else:
        hosting_charge_cents = base_hosting_cents

    use_dashboard_price = not vat_top_hosting
    line_items = _line_items_hosting(
        pkg,
        interval=interval,
        unit_amount_cents=hosting_charge_cents,
        allow_dashboard_price_id=use_dashboard_price,
    )

    dom_cents = domain_registration_eur_cents
    if dom_cents is not None and dom_cents > 0:
        if not _env_bool("STRIPE_CHECKOUT_DOMAIN_LINE_ITEM", True):
            log.info("domain line item omitted (STRIPE_CHECKOUT_DOMAIN_LINE_ITEM disabled)")
        else:
            if dom_cents > 5_000_000:
                raise ValueError("domain_registration_eur_cents prea mare")
            # Implicit: suma trimisă e TTC (ex. din catalog registrar). TVA separat doar dacă activați explicit.
            dcharge = int(dom_cents)
            if _env_bool("STRIPE_DOMAIN_CHARGE_VAT_ON_TOP", False):
                dcharge = int(round(dom_cents * (1.0 + float(vat_rate))))
            line_items = line_items + [_line_item_domain_one_time(dom, dcharge)]
            meta["domain_registration_eur_cents"] = str(int(dom_cents))

    session = await run_in_threadpool(
        lambda: stripe.checkout.Session.create(
            mode="subscription",
            line_items=line_items,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=meta,
        )
    )

    meta_blob = json.dumps(
        {"checkout": "create", "package": pkg, "interval": interval}, ensure_ascii=False
    )
    existing = await fetch_one(
        "SELECT id FROM hosting_orders WHERE stripe_checkout_session_id = ?",
        (session.id,),
    )
    if not existing:
        await execute_insert(
            """INSERT INTO hosting_orders (
                domain, package_tier, status, stripe_checkout_session_id, user_id, metadata_json
            ) VALUES (?, ?, 'pending_payment', ?, ?, ?)""",
            (dom, pkg, session.id, user_id, meta_blob),
        )
    log.info("hosting checkout session %s pending_payment %s %s", session.id, dom, pkg)
    return session
