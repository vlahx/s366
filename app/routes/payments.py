# Plăți unice (servicii) — separat de hosting / abonamente
import logging

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.utils.service_payment_checkout import create_service_checkout_session
from app.utils.service_payment_stripe import (
    construct_service_stripe_event,
    dispatch_service_stripe_event,
    mark_service_webhook_processed,
    service_webhook_should_process,
)

log = logging.getLogger(__name__)

router = APIRouter()
_templates_dir = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


class ServiceCheckoutBody(BaseModel):
    amount_eur: str | int | float
    description: str = Field(..., min_length=5, max_length=4000)


@router.get("/service")
async def service_payment_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="payments/service.html",
        context={"request": request},
    )


@router.get("/success")
async def payment_success(request: Request, session_id: str | None = None):
    return templates.TemplateResponse(
        request=request,
        name="payments/success.html",
        context={"request": request, "session_id": session_id},
    )


@router.get("/cancel")
async def payment_cancel(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="payments/cancel.html",
        context={"request": request},
    )


@router.post("/api/create-checkout-session")
async def create_service_checkout(request: Request, body: ServiceCheckoutBody):
    try:
        base = str(request.base_url).rstrip("/")
        raw_uid = request.session.get("user_id")
        user_id: int | None = None
        if raw_uid is not None:
            try:
                user_id = int(raw_uid)
            except (TypeError, ValueError):
                user_id = None
        session = await create_service_checkout_session(
            amount_eur=body.amount_eur,
            description=body.description,
            user_id=user_id,
            request_base_url=base,
        )
        url = session.url
        if not url:
            raise HTTPException(status_code=500, detail="Stripe nu a returnat URL")
        return JSONResponse({"url": url})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        log.exception("service checkout create failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/webhooks/stripe")
async def stripe_service_webhook(request: Request):
    """
    În Stripe Dashboard: endpoint separat față de /hosting/webhooks/stripe,
    același eveniment checkout.session.completed sau doar acest flux.
    Signing secret: STRIPE_SERVICE_WEBHOOK_SECRET (whsec_... din destinația pentru acest URL).
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = construct_service_stripe_event(payload, sig)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Semnătură Stripe invalidă")

    # stripe.Webhook.construct_event poate întoarce stripe.Event (StripeObject), nu dict.
    event = event.to_dict() if hasattr(event, "to_dict") else event

    event_id = event.get("id") if isinstance(event, dict) else None
    event_type = event.get("type") if isinstance(event, dict) else None
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Eveniment Stripe incomplet")

    if not await service_webhook_should_process(event_id, event_type):
        return JSONResponse({"received": True, "duplicate": True})

    try:
        await dispatch_service_stripe_event(event)
        await mark_service_webhook_processed(event_id, ok=True)
    except Exception as e:
        log.exception("Stripe service webhook procesare eșuată: %s", event_id)
        await mark_service_webhook_processed(event_id, ok=False, error=str(e))
        raise HTTPException(status_code=500, detail="Procesare eșuată") from e

    return JSONResponse({"received": True})
