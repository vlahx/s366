# app/routes/hosting.py
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.templating import Jinja2Templates

from app.utils.check_availability import check_domain_availability

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