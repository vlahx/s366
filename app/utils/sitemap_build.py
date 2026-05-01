"""
Generare sitemap.xml — URL-uri publice indexabile + extensie pentru conținut dinamic (ex. blog).
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Sequence

from app.utils.hosting_checkout import public_base_url


@dataclass(frozen=True)
class SitemapEntry:
    """O intrare în sitemap (path relativ la origin, începe cu /)."""

    path: str
    changefreq: str = "weekly"
    priority: float = 0.8

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError("path trebuie să înceapă cu /")
        if not (0.0 <= self.priority <= 1.0):
            raise ValueError("priority între 0 și 1")


def default_public_entries() -> list[SitemapEntry]:
    """
    Pagini statice + secțiuni publice. Adaugă aici rute noi când apar.
    Nu include: admin, auth, webhooks, API, plăți convenite (doar share).
    """
    return [
        SitemapEntry("/", changefreq="weekly", priority=1.0),
        SitemapEntry("/despre", changefreq="monthly", priority=0.9),
        SitemapEntry("/contact", changefreq="monthly", priority=0.9),
        SitemapEntry("/solutii", changefreq="monthly", priority=0.85),
        SitemapEntry("/terms", changefreq="yearly", priority=0.4),
        SitemapEntry("/privacy", changefreq="yearly", priority=0.4),
        SitemapEntry("/chat/", changefreq="weekly", priority=0.85),
        SitemapEntry("/hosting", changefreq="weekly", priority=0.9),
        SitemapEntry("/hosting/solutii-custom", changefreq="monthly", priority=0.75),
    ]


async def dynamic_entries() -> list[SitemapEntry]:
    """Index blog, categorii și articole publicate."""
    from app.utils.blog_db import list_categories, list_published_slugs_for_sitemap

    out: list[SitemapEntry] = [
        SitemapEntry("/blog/", changefreq="weekly", priority=0.85),
    ]
    for c in await list_categories():
        out.append(
            SitemapEntry(f"/blog/category/{c.slug}", changefreq="weekly", priority=0.65)
        )
    for slug in await list_published_slugs_for_sitemap():
        out.append(SitemapEntry(f"/blog/{slug}", changefreq="monthly", priority=0.7))
    return out


def site_origin(request_base: str | None) -> str:
    return public_base_url(request_base).rstrip("/")


def build_sitemap_xml(origin: str, entries: Sequence[SitemapEntry]) -> str:
    origin = origin.rstrip("/")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for e in entries:
        loc = origin + e.path
        loc_esc = html.escape(loc, quote=True)
        pr = f"{float(e.priority):.1f}"
        lines.append("  <url>")
        lines.append(f"    <loc>{loc_esc}</loc>")
        lines.append(f"    <changefreq>{html.escape(e.changefreq)}</changefreq>")
        lines.append(f"    <priority>{pr}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines)


def build_robots_txt(origin: str) -> str:
    origin = origin.rstrip("/")
    return f"""User-agent: *
Disallow: /admin/
Disallow: /company_admin/
Disallow: /auth/
Disallow: /hosting/api/
Disallow: /hosting/webhooks/
Disallow: /hosting/provision
Disallow: /hosting/checkout/
Disallow: /payments/
Disallow: /health
Disallow: /docs
Disallow: /redoc
Disallow: /openapi.json
Allow: /

Sitemap: {origin}/sitemap.xml
"""
