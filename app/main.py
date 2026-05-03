import sys
import os
import logging
import asyncio
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import RedirectResponse, FileResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.routes.chat import chat_home_page, router as chat_router
from app.routes.auth import router as auth_router
from app.routes.admin import router as admin_router
from app.routes.public import router as public_router
from app.routes.company_admin import router as company_admin_router
from app.routes.hosting import _hosting_home_page, router as hosting_router
from app.routes.payments import router as payments_router
from app.routes.seo import router as seo_router
from app.routes.blog import _norm_search, _render_blog_index, router as blog_router
from app.routes.blog_admin import router as blog_admin_router
from app.middleware.footer_page_views import FooterPageViewMiddleware

from app.models.sqlite_model import init_db
from app.utils.scheduler import start_global_scheduler
from app.utils.api_async import LLMServiceAsync, APIServiceAsync

# ... (toate os.environ și logging setup rămân la fel) ...


def _forwarded_scheme(scope: dict) -> str | None:
    """Citește X-Forwarded-Proto (trimis de Caddy) — fără ProxyHeadersMiddleware (Starlette vechi)."""
    for key, value in scope.get("headers") or []:
        if key == b"x-forwarded-proto":
            part = value.decode("latin1").split(",")[0].strip().lower()
            if part in ("https", "http"):
                return part
    return None


class ForwardedProtoMiddleware:
    """Pune scope['scheme'] la https când terminarea TLS e la Caddy (evită redirect-uri http://)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            proto = _forwarded_scheme(scope)
            if proto:
                scope = dict(scope)
                scope["scheme"] = proto
        await self.app(scope, receive, send)


class HeadToGetMiddleware:
    """
    Crawleri (Facebook, etc.) trimit des HEAD. Fără rute HEAD explicite → 405.
    Transformă HEAD în GET, rulează handler-ul GET, apoi taie corpul răspunsului
    (headerele rămân, inclusiv Content-Length — conform RFC).

    Trebuie să fie cel mai exterior (ultimul add_middleware), astfel încât
    SessionMiddleware și restul stack-ului văd deja method=GET — evită edge-case-uri
    cu sesiunea / cookie pe HEAD.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "HEAD":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if path.startswith("/static"):
            await self.app(scope, receive, send)
            return

        scope_get = dict(scope)
        scope_get["method"] = "GET"

        saw_start = False
        body_sent = False

        async def send_strip_body(message):
            nonlocal saw_start, body_sent
            if message["type"] == "http.response.start":
                await send(message)
                saw_start = True
            elif message["type"] == "http.response.body":
                if body_sent:
                    return
                if message.get("more_body"):
                    return
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                body_sent = True
            else:
                await send(message)

        await self.app(scope_get, receive, send_strip_body)
        if saw_start and not body_sent:
            await send({"type": "http.response.body", "body": b"", "more_body": False})

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Sistemul S366 AI pornește...")
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

# Middleware-uri — Caddy trimite de obicei X-Forwarded-Proto=https către upstream HTTP.
# add_middleware: primul în listă = cel mai „interior”; ultimul = primul care vede request-ul.
# Dorim: HeadToGet (exterior) → Session → ForwardedProto → rute.
app.add_middleware(ForwardedProtoMiddleware)
app.add_middleware(SessionMiddleware, secret_key="@Leia1990")
app.add_middleware(FooterPageViewMiddleware)
app.add_middleware(HeadToGetMiddleware)

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
app.include_router(seo_router, tags=["SEO"])
app.include_router(public_router, tags=["Public"])
app.include_router(blog_router, prefix="/blog", tags=["Blog"])
app.include_router(chat_router, prefix="/chat", tags=["Chat"])
app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])
app.include_router(blog_admin_router, prefix="/admin", tags=["Admin Blog"])
app.include_router(company_admin_router, prefix="/company_admin", tags=["Company Admin"])
app.include_router(hosting_router, prefix="/hosting", tags=["Hosting"])
app.include_router(payments_router, prefix="/payments", tags=["Payments"])

@app.get("/blog", include_in_schema=False)
async def blog_no_trailing_slash(
    request: Request,
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1, le=10_000),
):
    """Aceeași pagină ca /blog/ — fără redirect gol pentru crawleri / curl fără -L."""
    return await _render_blog_index(request, None, search=_norm_search(q), page=page)


@app.get("/chat", include_in_schema=False)
async def chat_no_trailing_slash(request: Request):
    """Aceeași pagină ca /chat/."""
    return await chat_home_page(request)


@app.get("/hosting", include_in_schema=False)
async def hosting_no_trailing_slash(request: Request):
    """Aceeași pagină ca /hosting/ — fără redirect. Curl fără -L și unii crawleri vedeau corp gol la 308."""
    return await _hosting_home_page(request)


@app.get("/health")
async def health_check():
    return {"status": "online", "engine": "FastAPI", "database": "aiosqlite"}