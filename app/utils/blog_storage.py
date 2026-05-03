"""Salvare fișiere upload blog în app/static/blog/ — raster: JPEG max 1200px latură lungă; GIF animat: original."""
from __future__ import annotations

import logging
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from PIL import Image

from app.utils.blog_image import resize_image_max_long_edge

log = logging.getLogger(__name__)

_ALLOWED = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
_BLOG_URL_PREFIX = "/static/blog/"
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def _blog_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "static" / "blog"


def normalize_static_blog_path(src: str | None) -> str | None:
    """Returnează `/static/blog/fișier.ext` dacă URL-ul indică un upload în blog, altfel None."""
    if not src:
        return None
    s = str(src).strip()
    if not s:
        return None
    s = s.split("?", 1)[0].split("#", 1)[0]
    if s.startswith(("http://", "https://", "//")):
        u = "https:" + s if s.startswith("//") else s
        path = urlparse(u).path or ""
    else:
        path = s if s.startswith("/") else f"/{s}"
    path = path.split("?", 1)[0]
    if path.startswith("static/blog/"):
        path = "/" + path
    if not path.startswith(_BLOG_URL_PREFIX):
        return None
    name = path[len(_BLOG_URL_PREFIX) :].strip("/")
    if not name or "/" in name or ".." in name:
        return None
    ext = Path(name).suffix.lower()
    if ext not in _ALLOWED:
        return None
    return f"{_BLOG_URL_PREFIX}{name}"


def _resolved_blog_file(normalized_path: str) -> Path | None:
    name = normalized_path.removeprefix(_BLOG_URL_PREFIX).strip("/")
    if not name or "/" in name:
        return None
    base = _blog_dir().resolve()
    cand = (base / name).resolve()
    try:
        cand.relative_to(base)
    except ValueError:
        return None
    return cand


def delete_blog_upload_by_url(src: str | None) -> bool:
    """Șterge fișierul de pe disc dacă `src` e un path sigur sub static/blog/."""
    norm = normalize_static_blog_path(src)
    if not norm:
        return False
    path = _resolved_blog_file(norm)
    if not path or not path.is_file():
        return False
    try:
        path.unlink()
        log.info("blog_storage: șters %s", path.name)
        return True
    except OSError as e:
        log.warning("blog_storage: nu pot șterge %s: %s", path, e)
        return False


def collect_blog_paths_from_html(html: str) -> list[str]:
    """Căi normalizate unice din `<img src>` care țintesc static/blog/."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in _IMG_SRC_RE.findall(html or ""):
        n = normalize_static_blog_path(raw)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def delete_blog_files_for_post(hero_image_url: str | None, content_html: str) -> None:
    """Șterge hero + toate imaginile din corp care sunt în static/blog/ (deduplicate)."""
    to_delete: set[str] = set()
    h = normalize_static_blog_path(hero_image_url)
    if h:
        to_delete.add(h)
    for p in collect_blog_paths_from_html(content_html):
        to_delete.add(p)
    for path in to_delete:
        delete_blog_upload_by_url(path)


def _referenced_blog_paths(hero_image_url: str | None, content_html: str) -> set[str]:
    refs: set[str] = set()
    h = normalize_static_blog_path(hero_image_url)
    if h:
        refs.add(h)
    for p in collect_blog_paths_from_html(content_html):
        refs.add(p)
    return refs


def delete_unreferenced_blog_uploads_after_edit(
    old_hero: str | None,
    old_html: str,
    new_hero: str | None,
    new_html: str,
) -> None:
    """
    După salvare la edit: șterge din disc orice fișier /static/blog/ care era la hero sau în HTML
    vechi și nu mai apare în hero + HTML nou (fără „bibliotecă media” — refolosești doar re-upload).
    """
    old_refs = _referenced_blog_paths(old_hero, old_html)
    new_refs = _referenced_blog_paths(new_hero, new_html)
    for path in old_refs - new_refs:
        delete_blog_upload_by_url(path)


def sanitize_upload_filename(name: str) -> str:
    base = (name or "upload").rsplit("/", 1)[-1]
    base = re.sub(r"[^a-zA-Z0-9._-]", "", base)[:120]
    return base or "upload"


def _is_animated_gif(data: bytes) -> bool:
    try:
        with Image.open(BytesIO(data)) as im:
            return im.format == "GIF" and getattr(im, "n_frames", 1) > 1
    except Exception:
        return False


async def save_blog_editor_image(data: bytes, original_filename: str) -> tuple[str, int, int]:
    """
    Returnează (URL relativ /static/blog/..., lățime, înălțime) pentru răspuns TinyMCE { location }.
    """
    ext = Path(sanitize_upload_filename(original_filename)).suffix.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    if ext not in _ALLOWED:
        raise ValueError("Format acceptat: JPEG, PNG, GIF, WebP")

    out_dir = _blog_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    if _is_animated_gif(data):
        with Image.open(BytesIO(data)) as im:
            w, h = im.size
        name = f"{uuid4().hex}.gif"
        (out_dir / name).write_bytes(data)
        return f"/static/blog/{name}", w, h

    try:
        out_bytes, (w, h) = resize_image_max_long_edge(data)
    except Exception:
        raise ValueError("Fișier imagine invalid sau corupt")

    name = f"{uuid4().hex}.jpg"
    (out_dir / name).write_bytes(out_bytes)
    return f"/static/blog/{name}", w, h
