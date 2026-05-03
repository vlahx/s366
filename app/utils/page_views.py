# Chei pentru contorul generic din footer (tabelul page_views).
from __future__ import annotations


def footer_page_view_key(path: str, method: str) -> str | None:
    """
    Cheie pentru increment în page_views sau None dacă pagina își gestionează singură
    contorul (blog, chat) sau nu e o pagină HTML de urmărit.
    """
    if method != "GET":
        return None
    path = path or "/"
    if not path.startswith("/"):
        path = "/" + path
    low = path.lower()
    if low.startswith("/static/") or low == "/static":
        return None
    if low == "/health" or low.startswith("/health/"):
        return None
    if low == "/sw.js":
        return None
    if low == "/sitemap.xml" or low == "/robots.txt":
        return None
    if low.startswith("/blog"):
        return None
    if low.startswith("/chat"):
        return None
    p = path.rstrip("/") or "/"
    if len(p) > 200:
        return None
    return f"path:{p}"
