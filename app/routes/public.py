from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.utils.blog_og import default_card_image_path
from app.utils.hosting_checkout import public_base_url

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _public_seo(request: Request, path: str) -> dict:
    """Canonical, og:url și og:image (card default). Titlul și descrierea OG vin din blocurile template, ca la home."""
    origin = public_base_url(str(request.base_url).rstrip("/"))
    path = (path or "/").strip()
    if not path.startswith("/"):
        path = "/" + path
    canonical = f"{origin}/" if path == "/" else f"{origin}{path}"
    return {
        "public_canonical": canonical,
        "seo_og_url": canonical,
        "seo_og_image_abs": f"{origin}{default_card_image_path()}",
    }


@router.get("/", response_class=HTMLResponse, name="index")
async def home(request: Request):
    ctx = {"request": request, **_public_seo(request, "/")}
    return templates.TemplateResponse(request=request, name="public/home.html", context=ctx)


@router.get("/terms", response_class=HTMLResponse, name="terms")
async def terms(request: Request):
    ctx = {"request": request, **_public_seo(request, "/terms")}
    return templates.TemplateResponse(request=request, name="public/terms.html", context=ctx)


@router.get("/privacy", response_class=HTMLResponse, name="privacy")
async def privacy(request: Request):
    ctx = {"request": request, **_public_seo(request, "/privacy")}
    return templates.TemplateResponse(request=request, name="public/privacy.html", context=ctx)


@router.get("/contact", response_class=HTMLResponse, name="contact")
async def contact(request: Request):
    ctx = {"request": request, **_public_seo(request, "/contact")}
    return templates.TemplateResponse(request=request, name="public/contact.html", context=ctx)


async def _despre_page(request: Request):
    ctx = {"request": request, **_public_seo(request, "/despre")}
    return templates.TemplateResponse(request=request, name="public/about.html", context=ctx)


@router.get("/despre", response_class=HTMLResponse, name="despre")
async def despre_noi(request: Request):
    return await _despre_page(request)


@router.get("/about", include_in_schema=False)
async def about_same_as_despre(request: Request):
    """Fără 308 — același HTML ca /despre; canonical rămâne /despre."""
    return await _despre_page(request)


##################################################################################
@router.get("/solutii", response_class=HTMLResponse, name="solutii")
async def solutii(request: Request):
    ctx = {"request": request, **_public_seo(request, "/solutii")}
    return templates.TemplateResponse(request=request, name="public/solutii.html", context=ctx)