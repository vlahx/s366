# 
import os
import logging
from fastapi import FastAPI, Request,HTTPException
from fastapi.responses import  RedirectResponse, FileResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from app.routes.chat import router as chat_router
from app.routes.auth import router as auth_router
from app.routes.admin import router as admin_router
from app.routes.public import router as public_router
from app.routes.company_admin import router as company_admin_router
from app.models.sqlite_model import init_db
from app.utils.api_async import LLMServiceAsync, APIServiceAsync



# Tăiem gura bibliotecilor de AI
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Setăm nivelul de logare la ERROR pentru a scăpa de WARNING și INFO inutile
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)

# Îi dăm „mute” la logger-ul de acces pentru ruta asta
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Dacă ruta e stats, returnăm False (adică NU logăm)
        return record.getMessage().find("/api/stats") == -1

# Aplicăm filtrul pe uvicorn.access
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    print("🚀 Sistemul s366_turbo pornește...")
    
    # 1. Inițializăm DB-ul asincron
    await init_db()
    
    # 2. Inițializăm serviciile și le stocăm în app.state
    # Asta previne re-pornirea thread-urilor la importuri circulare
    app.state.llm_service = LLMServiceAsync()
    app.state.api_service = APIServiceAsync()
    
    print("✅ Sistemul este online.")
    
    yield
    
    # --- SHUTDOWN ---
    print("🛑 Sistemul se închide curat.")
    # Aici poți adăuga app.state.llm_service.stop() dacă ai o metodă de cleanup

app = FastAPI(lifespan=lifespan)

# Adaugă asta în handler-ul tău din main.py
@app.exception_handler(404)
async def custom_404_handler(request: Request, __):
    return templates.TemplateResponse(
        "errors/404.html", 
        {"request": request}, 
        status_code=404
    )

# Handler pentru 403 - Acces Interzis
@app.exception_handler(403)
async def custom_403_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        "errors/403.html", 
        {"request": request, "detail": exc.detail}, 
        status_code=403
    )

# Handler pentru 401 - Neautorizat (Redirect la Login)
@app.exception_handler(401)
async def custom_401_handler(request: Request, exc: HTTPException):
    # Dacă nu e logat, cel mai bine e să-l trimitem direct la login
    request.session["flash_messages"] = [{"text": "Te rugăm să te autentifici.", "type": "warning"}]
    return RedirectResponse(url="/auth/login", status_code=303)


@app.get("/sw.js")
async def serve_service_worker():
    return FileResponse("app/static/sw.js", media_type="application/javascript")


# Middleware-uri
app.add_middleware(SessionMiddleware, secret_key="@Leia1990")

@app.middleware("http")
async def force_https_middleware(request: Request, call_next):
    # Corecție: Request trebuie să vină din fastapi, nu din urllib
    request.scope["scheme"] = "https"
    return await call_next(request)

# Static & Templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Include Routere
app.include_router(public_router, tags= ["Public"])
app.include_router(chat_router, prefix="/chat", tags=["Chat"])
app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])
app.include_router(company_admin_router, prefix="/company_admin", tags=["Company Admin"])

@app.get("/health")
async def health_check():
    return {
        "status": "online", 
        "engine": "FastAPI",
        "database": "aiosqlite"
    }