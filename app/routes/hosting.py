# app/routes/hosting.py
import logging
from pathlib import Path

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from fastapi.templating import Jinja2Templates

from app.utils.blog_og import default_card_image_path
from app.utils.check_availability import check_domain_availability
from app.utils.hosting_checkout import (
    create_hosting_checkout_session,
    public_base_url,
)
from app.utils.hosting_stripe import (
    construct_stripe_event,
    dispatch_stripe_event,
    mark_webhook_processed,
    webhook_should_process,
)

log = logging.getLogger(__name__)

HOSTING_META_DESCRIPTION = (
    "Îți oferim un website gata configurat, cu SSL, email, backup și mai mult. "
    "Magazin virtual sau blog în pachet."
)

router = APIRouter()
_templates_dir = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


async def _hosting_home_page(request: Request):
    """Pagina publică de hosting. /hosting și /hosting/ — același HTML; canonical rămâne cu slash final."""
    origin = public_base_url(str(request.base_url).rstrip("/"))
    hosting_canonical = f"{origin}/hosting/"
    # og:url = exact path-ul cererii — Facebook compară adesea cu URL-ul share-uit (/hosting vs /hosting/).
    seo_url = f"{origin}{request.url.path}"
    if request.url.query:
        seo_url = f"{seo_url}?{request.url.query}"
    return templates.TemplateResponse(
        request=request,
        name="hosting/index.html",
        context={
            "request": request,
            "hosting_canonical": hosting_canonical,
            "seo_og_url": seo_url,
            "hosting_meta_description": HOSTING_META_DESCRIPTION,
            "seo_og_image_abs": f"{origin}{default_card_image_path()}",
        },
    )


@router.get("/", response_class=HTMLResponse)
async def hosting_home(request: Request):
    return await _hosting_home_page(request)


async def _hosting_solutii_custom_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="hosting/solutii-custom.html",
        context={"request": request},
    )


@router.get("/solutii-custom", response_class=HTMLResponse)
async def hosting_custom_solutions(request: Request):
    return await _hosting_solutii_custom_page(request)


class DomainAvailabilityRequest(BaseModel):
    domain: str


class CheckoutSessionRequest(BaseModel):
    domain: str
    package_tier: str


async def _hosting_provision_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="hosting/provision.html",
        context={"request": request},
    )


@router.get("/provision", response_class=HTMLResponse)
async def hosting_provision(request: Request):
    return await _hosting_provision_page(request)


async def _hosting_checkout_success_page(
    request: Request, session_id: str | None = None
):
    return templates.TemplateResponse(
        request=request,
        name="hosting/checkout_success.html",
        context={"request": request, "session_id": session_id},
    )


@router.get("/checkout/success", response_class=HTMLResponse)
async def hosting_checkout_success(request: Request, session_id: str | None = None):
    return await _hosting_checkout_success_page(request, session_id)


async def _hosting_checkout_cancel_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="hosting/checkout_cancel.html",
        context={"request": request},
    )


@router.get("/checkout/cancel", response_class=HTMLResponse)
async def hosting_checkout_cancel(request: Request):
    return await _hosting_checkout_cancel_page(request)


@router.post("/api/create-checkout-session")
async def hosting_create_checkout_session(request: Request, body: CheckoutSessionRequest):
    """Creează sesiune Stripe Checkout (live sau test, după cheia STRIPE_SECRET_KEY)."""
    try:
        base = str(request.base_url).rstrip("/")
        raw_uid = request.session.get("user_id")
        user_id: int | None = None
        if raw_uid is not None:
            try:
                user_id = int(raw_uid)
            except (TypeError, ValueError):
                user_id = None
        session = await create_hosting_checkout_session(
            domain=body.domain,
            package_tier=body.package_tier,
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
        log.exception("Stripe checkout create failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


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