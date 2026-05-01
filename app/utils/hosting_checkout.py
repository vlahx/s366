"""
Creare Stripe Checkout pentru hosting (abonament lunar EUR).
Necesită STRIPE_SECRET_KEY. Opțional: PUBLIC_SITE_URL (ex. https://s366.online).
Opțional: STRIPE_PRICE_ID_STARTER | _PRO | _BUSINESS — altfel se folosește price_data.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import stripe
from starlette.concurrency import run_in_threadpool

from app.models.sqlite_model import execute_insert, fetch_one

log = logging.getLogger(__name__)

PACKAGE_EUR_CENTS: dict[str, int] = {
    "starter": 300,
    "pro": 500,
    "business": 1000,
}


def _stripe_secret() -> str:
    key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY lipsește din mediu")
    return key


def public_base_url(request_base_url: str | None) -> str:
    env = os.getenv("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if env:
        return env
    if request_base_url:
        return str(request_base_url).rstrip("/")
    return "https://s366.online"


def _line_items(package_tier: str) -> list[dict[str, Any]]:
    tid = package_tier.lower()
    env_key = f"STRIPE_PRICE_ID_{tid.upper()}"
    price_id = os.getenv(env_key, "").strip()
    if price_id:
        return [{"price": price_id, "quantity": 1}]
    if tid not in PACKAGE_EUR_CENTS:
        raise ValueError("Pachet invalid")
    cents = PACKAGE_EUR_CENTS[tid]
    return [
        {
            "price_data": {
                "currency": "eur",
                "product_data": {"name": f"S366 AI Hosting — {tid}"},
                "recurring": {"interval": "month"},
                "unit_amount": cents,
            },
            "quantity": 1,
        }
    ]


async def create_hosting_checkout_session(
    *,
    domain: str,
    package_tier: str,
    user_id: int | None,
    request_base_url: str | None,
) -> stripe.checkout.Session:
    dom = domain.strip().lower().rstrip(".")
    pkg = package_tier.strip().lower()
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

    meta: dict[str, str] = {"domain": dom, "package_tier": pkg}
    if user_id is not None:
        meta["user_id"] = str(user_id)

    line_items = _line_items(pkg)

    session = await run_in_threadpool(
        lambda: stripe.checkout.Session.create(
            mode="subscription",
            line_items=line_items,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=meta,
        )
    )

    meta_blob = json.dumps({"checkout": "create", "package": pkg}, ensure_ascii=False)
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
