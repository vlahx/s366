"""Open Graph pentru articole blog — URL canonic, descriere scurtată, dimensiuni imagine."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.utils.hosting_checkout import public_base_url

_OG_DESC_MAX = 300
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_OG_RASTER_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def site_origin(request_base: str | None) -> str:
    return public_base_url(request_base).rstrip("/")


def truncate_og_description(text: str, max_chars: int = _OG_DESC_MAX) -> str:
    s = " ".join((text or "").split())
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def extract_first_image_from_html(html: str) -> str | None:
    for u in _IMG_SRC_RE.findall(html or ""):
        u = (u or "").strip()
        if u:
            return u
    return None


def _is_raster_public_path(path: str) -> bool:
    p = (path.split("?", 1)[0] or "").lower()
    return Path(p).suffix in _OG_RASTER_SUFFIXES


def canonical_image_url(origin: str, src: str | None) -> str | None:
    """Transformă path relativ sau URL local în URL absolut pe domeniul public."""
    if not src or not str(src).strip():
        return None
    s = str(src).strip()
    origin = origin.rstrip("/")
    if s.startswith(("http://", "https://")):
        p = urlparse(s)
        if (p.hostname or "").lower() in ("localhost", "127.0.0.1"):
            return f"{origin}{p.path or ''}" + (f"?{p.query}" if p.query else "")
        return s
    if s.startswith("//"):
        return f"https:{s}"
    path = s if s.startswith("/") else f"/{s}"
    if not _is_raster_public_path(path):
        return None
    return f"{origin}{path}"


def default_card_image_path() -> str:
    return "/static/images/og/chat-ai-s366.png"


@dataclass(frozen=True)
class BlogOgBundle:
    image_abs: str
    image_width: int | None
    image_height: int | None
    description: str
    is_default_card: bool


def _plain_strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "", flags=re.S)


def og_description_for_post(title: str, excerpt: str, content_html: str) -> str:
    for candidate in (excerpt, _plain_strip_html(content_html), title):
        c = (candidate or "").strip()
        if c:
            return truncate_og_description(c)
    return truncate_og_description(title or "S366 AI")


def build_post_og(
    *,
    request_base: str | None,
    title: str,
    excerpt: str,
    content_html: str,
    hero_image_url: str | None,
    og_image_width: int | None,
    og_image_height: int | None,
) -> BlogOgBundle:
    origin = site_origin(request_base)
    desc = og_description_for_post(title, excerpt, content_html)
    hero = (hero_image_url or "").strip() or None
    first = extract_first_image_from_html(content_html)
    for cand in (hero, first):
        abs_u = canonical_image_url(origin, cand)
        if abs_u:
            return BlogOgBundle(
                image_abs=abs_u,
                image_width=og_image_width,
                image_height=og_image_height,
                description=desc,
                is_default_card=False,
            )
    card = f"{origin}{default_card_image_path()}"
    return BlogOgBundle(
        image_abs=card,
        image_width=1200,
        image_height=630,
        description=desc,
        is_default_card=True,
    )


def published_utc(dt: datetime | None, fallback: datetime | None = None) -> datetime:
    d = dt or fallback or datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)
