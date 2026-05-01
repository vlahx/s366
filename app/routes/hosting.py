# app/routes/hosting.py
import logging
from pathlib import Path

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.templating import Jinja2Templates

from app.utils.check_availability import check_domain_availability
from app.utils.hosting_stripe import (
    construct_stripe_event,
    dispatch_stripe_event,
    mark_webhook_processed,
    webhook_should_process,
)

log = logging.getLogger(__name__)

router = APIRouter()
_templates_dir = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

@router.get("/")
async def hosting_home(request: Request):
    """Pagina publică de hosting. Se accesează via /hosting"""
    return templates.TemplateResponse(request=request, name="hosting/index.html", context={"request": request})


@router.get("/solutii-custom")
async def hosting_custom_solutions(request: Request):
    """Soluții la cerere: hosting aplicații firmă, AI pe date, RAG, dezvoltare custom."""
    return templates.TemplateResponse(
        request=request,
        name="hosting/solutii-custom.html",
        context={"request": request},
    )


class DomainAvailabilityRequest(BaseModel):
    domain: str


@router.post("/check-availability")
async def check_availability(payload: DomainAvailabilityRequest):
    result = await check_domain_availability(payload.domain)
    return JSONResponse(content=result.to_dict())


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """
    Webhook Stripe (ex: checkout.session.completed).
    Dashboard Stripe → Developers → Webhooks → URL: https://<domeniu>/hosting/webhooks/stripe
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = construct_stripe_event(payload, sig)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Semnătură Stripe invalidă")

    event_id = event.get("id")
    event_type = event.get("type")
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Eveniment Stripe incomplet")

    if not await webhook_should_process(event_id, event_type):
        return JSONResponse({"received": True, "duplicate": True})

    try:
        await dispatch_stripe_event(event)
        await mark_webhook_processed(event_id, ok=True)
    except Exception as e:
        log.exception("Stripe webhook procesare eșuată: %s", event_id)
        await mark_webhook_processed(event_id, ok=False, error=str(e))
        raise HTTPException(status_code=500, detail="Procesare eșuată") from e

    return JSONResponse({"received": True})