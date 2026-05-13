# app/routes/hosting.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import quote

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from fastapi.templating import Jinja2Templates

from app.utils.blog_og import default_card_image_path
from app.utils.check_availability import (
    check_domain_availability,
    domain_catalog_gross_cents_from_details,
    normalize_domain,
)
from app.utils.hosting_pricing_display import build_hosting_pricing_context
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
from app.models.sqlite_model import fetch_one
from app.utils.billing_profile import billing_readiness

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
            "hosting_pricing_json": json.dumps(
                await build_hosting_pricing_context(), ensure_ascii=False
            ),
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
    hosting_billing_interval: str = "month"
    # True = utilizatorul aduce domeniul; fără linie „înregistrare domeniu” în Stripe.
    bring_own_domain: bool = False


async def _hosting_provision_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="hosting/provision.html",
        context={
            "request": request,
            "hosting_pricing_json": json.dumps(
                await build_hosting_pricing_context(), ensure_ascii=False
            ),
        },
    )


@router.get("/provision", response_class=HTMLResponse)
async def hosting_provision(request: Request):
    raw_uid = request.session.get("user_id")
    qs = request.url.query
    self_path = f"/hosting/provision?{qs}" if qs else "/hosting/provision"
    if not raw_uid:
        return RedirectResponse(
            url=f"/auth/login?next={quote(self_path)}",
            status_code=303,
        )
    try:
        user_id = int(raw_uid)
    except (TypeError, ValueError):
        return RedirectResponse(
            url=f"/auth/login?next={quote(self_path)}",
            status_code=303,
        )
    user_row = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user_row:
        return RedirectResponse(
            url=f"/auth/login?next={quote(self_path)}",
            status_code=303,
        )
    user_d = dict(user_row)
    company = None
    if user_d.get("company_id"):
        company = await fetch_one(
            "SELECT * FROM companies WHERE company_id = ?",
            (user_d["company_id"],),
        )
    if not billing_readiness(user_d, dict(company) if company else None)["ok"]:
        return RedirectResponse(
            url=f"/auth/billing?next={quote(self_path)}",
            status_code=303,
        )
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
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Autentificare necesară. Intră în cont, apoi încearcă din nou plata.",
            )
        user_row = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
        if not user_row:
            raise HTTPException(status_code=401, detail="Sesiune invalidă.")
        user_d = dict(user_row)
        company_row = None
        if user_d.get("company_id"):
            company_row = await fetch_one(
                "SELECT * FROM companies WHERE company_id = ?",
                (user_d["company_id"],),
            )
        if not billing_readiness(user_d, dict(company_row) if company_row else None)[
            "ok"
        ]:
            raise HTTPException(
                status_code=400,
                detail="Completează datele de facturare (PF sau PJ) la /auth/billing înainte de plată.",
            )

        dom = normalize_domain(body.domain)
        if not dom or "." not in dom:
            raise HTTPException(status_code=400, detail="Domeniu invalid.")

        reg_cents: int | None = None
        if not body.bring_own_domain:
            avail = await check_domain_availability(body.domain)
            if not avail.available:
                raise HTTPException(
                    status_code=400,
                    detail="Domeniul nu e disponibil pentru înregistrare. Revino la /hosting și verifică din nou.",
                )
            dom = avail.domain
            reg_cents = domain_catalog_gross_cents_from_details(avail.details)

        raw_iv = (body.hosting_billing_interval or "month").strip().lower()
        if raw_iv not in ("month", "year"):
            raise HTTPException(
                status_code=400,
                detail="Perioadă de facturare invalidă. Alege lunar sau anual.",
            )
        session = await create_hosting_checkout_session(
            domain=dom,
            package_tier=body.package_tier,
            user_id=user_id,
            request_base_url=base,
            hosting_billing_interval=raw_iv,
            domain_registration_eur_cents=reg_cents,
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

    # stripe.Webhook.construct_event poate întoarce stripe.Event (StripeObject), nu dict.
    event = event.to_dict() if hasattr(event, "to_dict") else event

    event_id = event.get("id") if isinstance(event, dict) else None
    event_type = event.get("type") if isinstance(event, dict) else None
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