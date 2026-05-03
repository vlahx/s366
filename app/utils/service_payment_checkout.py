"""
Checkout Stripe pentru plăți unice (servicii: mentenanță, instalare, etc.).
Metadata: payment_kind=service. Webhook dedicat: POST /payments/webhooks/stripe
"""
from __future__ import annotations

import json
import logging
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import stripe
from starlette.concurrency import run_in_threadpool

from app.models.sqlite_model import execute_insert, fetch_one
from app.utils.hosting_checkout import _stripe_secret, public_base_url

log = logging.getLogger(__name__)

_STRIPE_META_MAX = 500


def _eur_bounds() -> tuple[Decimal, Decimal]:
    lo = Decimal(os.getenv("SERVICE_PAYMENT_MIN_EUR", "1"))
    hi = Decimal(os.getenv("SERVICE_PAYMENT_MAX_EUR", "25000"))
    if lo < Decimal("0.50"):
        lo = Decimal("0.50")
    if hi > Decimal("100000"):
        hi = Decimal("100000")
    if hi < lo:
        hi = lo
    return lo, hi


def parse_amount_eur(raw: str | float | int) -> int:
    """Validează suma și returnează cenți EUR (int)."""
    lo, hi = _eur_bounds()
    try:
        d = Decimal(str(raw).strip().replace(",", "."))
    except Exception as e:
        raise ValueError("Sumă invalidă") from e
    if d != d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
        raise ValueError("Folosește cel mult 2 zecimale")
    if d < lo or d > hi:
        raise ValueError(f"Suma trebuie să fie între {lo} și {hi} EUR")
    cents = int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents < 1:
        raise ValueError("Sumă prea mică")
    return cents


def normalize_description(raw: str) -> str:
    s = (raw or "").strip()
    if len(s) < 5:
        raise ValueError("Descrierea trebuie să aibă cel puțin 5 caractere")
    if len(s) > 4000:
        raise ValueError("Descrierea e prea lungă (max. 4000 caractere)")
    s = re.sub(r"\s+", " ", s)
    return s


async def create_service_checkout_session(
    *,
    amount_eur: str | float | int,
    description: str,
    user_id: int | None,
    request_base_url: str | None,
) -> stripe.checkout.Session:
    cents = parse_amount_eur(amount_eur)
    desc = normalize_description(description)

    stripe.api_key = _stripe_secret()
    base = public_base_url(request_base_url)
    success_url = f"{base}/payments/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/payments/cancel"

    meta_desc = desc[:_STRIPE_META_MAX]
    meta: dict[str, str] = {
        "payment_kind": "service",
        "description": meta_desc,
    }
    if user_id is not None:
        meta["user_id"] = str(user_id)

        line_name = f"S366 AI — serviciu"
    if len(desc) <= 200:
        line_name = f"S366 AI — {desc}"[:500]

    session = await run_in_threadpool(
        lambda: stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "eur",
                        "product_data": {"name": line_name[:500]},
                        "unit_amount": cents,
                    },
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=meta,
        )
    )

    meta_blob = json.dumps(
        {"checkout": "service_payment", "description": desc, "amount_cents": cents},
        ensure_ascii=False,
    )
    existing = await fetch_one(
        "SELECT id FROM service_payments WHERE stripe_checkout_session_id = ?",
        (session.id,),
    )
    if not existing:
        await execute_insert(
            """INSERT INTO service_payments (
                description, amount_cents, currency, status,
                stripe_checkout_session_id, user_id, metadata_json
            ) VALUES (?, ?, 'eur', 'pending_payment', ?, ?, ?)""",
            (desc, cents, session.id, user_id, meta_blob),
        )
    log.info("service_payment checkout session %s pending %s cents", session.id, cents)
    return session
