"""
Stripe webhook + persistență comenzi hosting (înainte de provisioning efectiv).
Variabile: STRIPE_WEBHOOK_SECRET (obligatoriu în producție), opțional STRIPE_SECRET_KEY pentru Checkout.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import stripe

from app.models.sqlite_model import execute_insert, execute_query, fetch_one, get_db

log = logging.getLogger(__name__)


def construct_stripe_event(payload: bytes, sig_header: str | None) -> dict[str, Any]:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET nu e setat în mediu")
    if not sig_header:
        raise ValueError("Lipsește header-ul stripe-signature")
    return stripe.Webhook.construct_event(payload, sig_header, secret)


async def webhook_should_process(event_id: str, event_type: str) -> bool:
    """
    Idempotency: dacă evenimentul e deja processed_ok=1, returnează False.
    Altfel asigură rândul (INSERT OR IGNORE) și returnează True pentru procesare.
    """
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO stripe_webhook_events
               (event_id, event_type, processed_ok) VALUES (?, ?, 0)""",
            (event_id, event_type),
        )
        await db.commit()
        async with db.execute(
            "SELECT processed_ok FROM stripe_webhook_events WHERE event_id = ?",
            (event_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return True
        return row["processed_ok"] != 1
    finally:
        await db.close()


async def mark_webhook_processed(event_id: str, *, ok: bool, error: str | None = None) -> None:
    if ok:
        await execute_query(
            """UPDATE stripe_webhook_events
               SET processed_ok = 1, last_error = NULL
               WHERE event_id = ?""",
            (event_id,),
        )
    else:
        await execute_query(
            """UPDATE stripe_webhook_events
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


async def process_checkout_session_completed(session: dict[str, Any]) -> None:
    session_id = session.get("id")
    if not session_id:
        raise ValueError("checkout.session fără id")

    meta = _meta(session)
    if (meta.get("payment_kind") or "").strip().lower() == "service":
        log.debug("checkout %s: plată servicii — procesat de /payments/webhooks/stripe", session_id)
        return

    domain = (meta.get("domain") or "").strip().lower().rstrip(".")
    package_tier = (
        meta.get("package_tier") or meta.get("package") or "unknown"
    ).strip() or "unknown"

    if not domain:
        raise ValueError("Metadata Stripe: lipsește «domain»")

    pi = session.get("payment_intent")
    if isinstance(pi, dict):
        pi = pi.get("id")
    cust = session.get("customer")
    if isinstance(cust, dict):
        cust = cust.get("id")

    meta_blob = json.dumps(dict(meta), ensure_ascii=False)

    existing = await fetch_one(
        "SELECT id FROM hosting_orders WHERE stripe_checkout_session_id = ?",
        (session_id,),
    )
    if existing:
        await execute_query(
            """UPDATE hosting_orders SET
                status = 'paid',
                domain = ?,
                package_tier = ?,
                stripe_payment_intent_id = ?,
                stripe_customer_id = ?,
                updated_at = datetime('now'),
                metadata_json = ?,
                last_error = NULL
            WHERE stripe_checkout_session_id = ?""",
            (domain, package_tier, pi, cust, meta_blob, session_id),
        )
        log.info("hosting_orders: actualizat paid pentru sesiunea %s (%s)", session_id, domain)
    else:
        await execute_insert(
            """INSERT INTO hosting_orders (
                domain, package_tier, status,
                stripe_checkout_session_id, stripe_payment_intent_id,
                stripe_customer_id, metadata_json
            ) VALUES (?, ?, 'paid', ?, ?, ?, ?)""",
            (domain, package_tier, session_id, pi, cust, meta_blob),
        )
        log.info("hosting_orders: creat paid pentru sesiunea %s (%s)", session_id, domain)


async def dispatch_stripe_event(event: dict[str, Any]) -> None:
    et = event.get("type")
    data = (event.get("data") or {}).get("object")
    if et == "checkout.session.completed" and isinstance(data, dict):
        await process_checkout_session_completed(data)
        return
    log.debug("Stripe event ignorat: %s", et)
