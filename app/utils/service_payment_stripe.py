"""
Webhook Stripe pentru plăți servicii (plată unică).
Env: STRIPE_SERVICE_WEBHOOK_SECRET (semnătură pentru endpoint-ul /payments/webhooks/stripe).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import stripe

from app.models.sqlite_model import execute_insert, execute_query, fetch_one, get_db

log = logging.getLogger(__name__)


def construct_service_stripe_event(payload: bytes, sig_header: str | None) -> dict[str, Any]:
    secret = os.getenv("STRIPE_SERVICE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise RuntimeError("STRIPE_SERVICE_WEBHOOK_SECRET nu e setat în mediu")
    if not sig_header:
        raise ValueError("Lipsește header-ul stripe-signature")
    return stripe.Webhook.construct_event(payload, sig_header, secret)


async def service_webhook_should_process(event_id: str, event_type: str) -> bool:
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO stripe_service_webhook_events
               (event_id, event_type, processed_ok) VALUES (?, ?, 0)""",
            (event_id, event_type),
        )
        await db.commit()
        async with db.execute(
            "SELECT processed_ok FROM stripe_service_webhook_events WHERE event_id = ?",
            (event_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return True
        return row["processed_ok"] != 1
    finally:
        await db.close()


async def mark_service_webhook_processed(event_id: str, *, ok: bool, error: str | None = None) -> None:
    if ok:
        await execute_query(
            """UPDATE stripe_service_webhook_events
               SET processed_ok = 1, last_error = NULL
               WHERE event_id = ?""",
            (event_id,),
        )
    else:
        await execute_query(
            """UPDATE stripe_service_webhook_events
               SET last_error = ?
               WHERE event_id = ?""",
            ((error or "")[:2000], event_id),
        )


def _meta(session: dict[str, Any]) -> dict[str, Any]:
    m = session.get("metadata")
    if m is None:
        return {}
    if isinstance(m, dict):
        return m
    return {}


async def process_service_checkout_completed(session: dict[str, Any]) -> None:
    session_id = session.get("id")
    if not session_id:
        raise ValueError("checkout.session fără id")

    meta = _meta(session)
    if (meta.get("payment_kind") or "").strip().lower() != "service":
        raise ValueError("Nu e o sesiune de plată servicii (metadata)")

    mode = (session.get("mode") or "").strip()
    if mode != "payment":
        raise ValueError("Așteptat mode=payment pentru servicii")

    pi = session.get("payment_intent")
    if isinstance(pi, dict):
        pi = pi.get("id")

    amount_total = session.get("amount_total")
    currency = (session.get("currency") or "eur").lower()

    meta_blob = json.dumps(dict(meta), ensure_ascii=False)

    existing = await fetch_one(
        "SELECT id FROM service_payments WHERE stripe_checkout_session_id = ?",
        (session_id,),
    )
    if existing:
        await execute_query(
            """UPDATE service_payments SET
                status = 'paid',
                stripe_payment_intent_id = ?,
                updated_at = datetime('now'),
                metadata_json = ?,
                last_error = NULL
            WHERE stripe_checkout_session_id = ?""",
            (pi, meta_blob, session_id),
        )
        log.info("service_payments: paid pentru sesiunea %s", session_id)
    else:
        desc = (meta.get("description") or "Serviciu S366 AI").strip() or "Serviciu S366 AI"
        cents = int(amount_total) if amount_total is not None else 0
        await execute_insert(
            """INSERT INTO service_payments (
                description, amount_cents, currency, status,
                stripe_checkout_session_id, stripe_payment_intent_id, metadata_json
            ) VALUES (?, ?, ?, 'paid', ?, ?, ?)""",
            (desc, cents, currency, session_id, pi, meta_blob),
        )
        log.info("service_payments: creat paid (webhook prim) sesiunea %s", session_id)


async def dispatch_service_stripe_event(event: dict[str, Any]) -> None:
    et = event.get("type")
    data = (event.get("data") or {}).get("object")
    if et == "checkout.session.completed" and isinstance(data, dict):
        await process_service_checkout_completed(data)
        return
    log.debug("Stripe service webhook ignorat: %s", et)
