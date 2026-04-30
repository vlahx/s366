from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse, name="index")
async def home(request: Request):
    # Aici poți trimite variabile dacă vrei să afișezi ceva dinamic pe prima pagină
    return templates.TemplateResponse(request=request, name="public/home.html", context={"request": request})

@router.get("/terms", response_class=HTMLResponse, name="terms")
async def terms(request: Request):
    return templates.TemplateResponse(request=request, name="public/terms.html", context={"request": request})

@router.get("/privacy", response_class=HTMLResponse, name="privacy")
async def privacy(request: Request):
    return templates.TemplateResponse(request=request, name="public/privacy.html", context={"request": request})

@router.get("/contact", response_class=HTMLResponse, name="contact")
async def contact(request: Request):
    return templates.TemplateResponse(request=request, name="public/contact.html", context={"request": request})

##################################################################################
@router.get("/solutii", response_class=HTMLResponse, name="solutii")
async def solutii(request: Request):
    # Aici poți trimite variabile dacă vrei să afișezi ceva dinamic pe prima pagină
    return templates.TemplateResponse(request=request, name="public/solutii.html", context={"request": request})