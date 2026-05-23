from __future__ import annotations

from app.utils.blog_db import increment_listing_page_views
from app.utils.page_views import footer_page_view_key


class FooterPageViewMiddleware:
    """
    Incrementează page_views pentru rutele care nu au contor dedicat (blog/chat).
    ASGI pur (fără BaseHTTPMiddleware) — BaseHTTPMiddleware rupe intermitent request.session.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            state = scope.setdefault("state", {})
            state["footer_view_count"] = None
            path = scope.get("path") or ""
            method = scope.get("method") or "GET"
            key = footer_page_view_key(path, method)
            if key:
                state["footer_view_count"] = await increment_listing_page_views(key)
        await self.app(scope, receive, send)
