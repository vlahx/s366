from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.utils.blog_db import increment_listing_page_views
from app.utils.page_views import footer_page_view_key


class FooterPageViewMiddleware(BaseHTTPMiddleware):
    """
    Incrementează page_views pentru rutele care nu au contor dedicat (blog/chat).
    Nu citește request.session, CSRF sau auth — nu poate produce 403 din „sesiune lipsă”.
    """

    async def dispatch(self, request: Request, call_next):
        request.state.footer_view_count = None
        key = footer_page_view_key(request.url.path, request.method)
        if key:
            request.state.footer_view_count = await increment_listing_page_views(key)
        return await call_next(request)
