# app/routes/hosting.py
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
_templates_dir = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

@router.get("/")
async def hosting_home(request: Request):
    """Pagina publică de hosting. Se accesează via /hosting"""
    return templates.TemplateResponse(request=request, name="hosting/index.html", context={"request": request})