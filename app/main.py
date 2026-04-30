import sys
import os
import logging
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.routes.chat import router as chat_router
from app.routes.auth import router as auth_router
from app.routes.admin import router as admin_router
from app.routes.public import router as public_router
from app.routes.company_admin import router as company_admin_router
from app.routes.hosting import router as hosting_router

from app.models.sqlite_model import init_db
from app.utils.scheduler import start_global_scheduler
from app.utils.api_async import LLMServiceAsync, APIServiceAsync

# ... (toate os.environ și logging setup rămân la fel) ...

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Sistemul s366_turbo pornește...")
    await init_db()
    app.state.llm_service = LLMServiceAsync()
    app.state.api_service = APIServiceAsync()
    app.state.scheduler_task = asyncio.create_task(start_global_scheduler())
    print("✅ Sistemul este online.")
    yield
    print("🛑 Sistemul se închide curat.")
    if hasattr(app.state, 'scheduler_task'):
        app.state.scheduler_task.cancel()
        try:
            await app.state.scheduler_task
        except asyncio.CancelledError:
            pass

app = FastAPI(lifespan=lifespan)

# Middleware-uri
app.add_middleware(SessionMiddleware, secret_key="@Leia1990")

# ✅ Static & Templates (definite ACUM, înainte de handlers)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ✅ Exception Handlers (acum pot folosi 'templates' sigur)
@app.exception_handler(404)
async def custom_404_handler(request: Request, __):
    return templates.TemplateResponse(request=request, name="errors/404.html", context={}, status_code=404)

@app.exception_handler(403)
async def custom_403_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse(request=request, name="errors/403.html", context={"detail": exc.detail}, status_code=403)

@app.exception_handler(401)
async def custom_401_handler(request: Request, exc: HTTPException):
    request.session["flash_messages"] = [{"text": "Te rugăm să te autentifici.", "type": "warning"}]
    return RedirectResponse(url="/auth/login", status_code=303)

@app.get("/sw.js")
async def serve_service_worker():
    return FileResponse("app/static/sw.js", media_type="application/javascript")

# ✅ Include Routere
app.include_router(public_router, tags=["Public"])
app.include_router(chat_router, prefix="/chat", tags=["Chat"])
app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])
app.include_router(company_admin_router, prefix="/company_admin", tags=["Company Admin"])
app.include_router(hosting_router, prefix="/hosting", tags=["Hosting"])

@app.get("/health")
async def health_check():
    return {"status": "online", "engine": "FastAPI", "database": "aiosqlite"}