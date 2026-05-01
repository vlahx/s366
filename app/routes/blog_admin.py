# Admin blog — doar superadmin (Depends pe router)
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from slugify import slugify

from app.utils.blog_db import (
    admin_delete_post,
    admin_get_post_by_slug,
    admin_list_all_posts,
    admin_upsert_post,
    list_categories,
)
from app.utils.blog_storage import (
    delete_blog_files_for_post,
    delete_unreferenced_blog_uploads_after_edit,
    save_blog_editor_image,
)
from app.utils.decorators import superadmin_required
from app.utils.hosting_checkout import public_base_url

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/blog",
    tags=["Admin Blog"],
    dependencies=[Depends(superadmin_required)],
)
_templates_dir = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def _flash(request: Request, text: str, typ: str = "info") -> None:
    prev = request.session.get("flash_messages") or []
    prev.append({"text": text, "type": typ})
    request.session["flash_messages"] = prev


def _parse_published_at(raw: str | None) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


@router.get("/")
async def blog_admin_root():
    return RedirectResponse(url="/admin/blog/posts", status_code=302)


@router.get("/posts")
async def blog_admin_list(request: Request):
    posts = await admin_list_all_posts()
    return templates.TemplateResponse(
        request=request,
        name="admin/blog_list.html",
        context={"request": request, "posts": posts, "title": "Administrare blog — S366 AI"},
    )


@router.get("/nou")
async def blog_admin_new(request: Request):
    cats = await list_categories()
    base = public_base_url(str(request.base_url).rstrip("/"))
    return templates.TemplateResponse(
        request=request,
        name="admin/blog_editor.html",
        context={
            "request": request,
            "post": None,
            "categories": cats,
            "editor_document_base": f"{base}/",
            "published_at_local": "",
            "title": "Articol nou — S366 AI Blog (admin)",
        },
    )


@router.get("/editare/{slug}")
async def blog_admin_edit(request: Request, slug: str):
    post = await admin_get_post_by_slug(slug)
    if not post:
        raise HTTPException(status_code=404, detail="Articol inexistent")
    cats = await list_categories()
    base = public_base_url(str(request.base_url).rstrip("/"))
    pub_local = ""
    if post.published_at:
        dt = post.published_at
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        pub_local = dt.strftime("%Y-%m-%dT%H:%M")
    return templates.TemplateResponse(
        request=request,
        name="admin/blog_editor.html",
        context={
            "request": request,
            "post": post,
            "categories": cats,
            "editor_document_base": f"{base}/",
            "published_at_local": pub_local,
            "title": f"Editare articol — {post.title} — S366 AI Blog (admin)",
        },
    )


@router.post("/salveaza")
async def blog_admin_save(request: Request):
    form = await request.form()
    title = (form.get("title") or "").strip()
    slug_in = (form.get("slug") or "").strip().lower()
    original_slug = (form.get("original_slug") or "").strip().lower()
    excerpt = (form.get("excerpt") or "").strip()
    content_html = (form.get("content_html") or "").strip()
    cat_raw = form.get("category_id")
    category_id: int | None = None
    if cat_raw not in (None, ""):
        try:
            category_id = int(cat_raw)
        except (TypeError, ValueError):
            category_id = None

    draft = form.get("draft") == "on"
    clear_hero = form.get("clear_hero") == "on"
    published_raw = form.get("published_at")

    final_slug = slug_in or slugify(title, lowercase=True) or "articol"
    if original_slug:
        final_slug = original_slug

    published_at = _parse_published_at(str(published_raw) if published_raw else None)
    if not draft and published_at is None:
        published_at = datetime.now(timezone.utc)

    existing = await admin_get_post_by_slug(final_slug) if original_slug else None
    hero_url: str | None = existing.hero_image_url if existing else None
    og_w: int | None = existing.og_image_width if existing else None
    og_h: int | None = existing.og_image_height if existing else None

    if clear_hero:
        hero_url = None
        og_w = og_h = None

    hero_field = form.get("hero")
    if hero_field is not None and hasattr(hero_field, "read"):
        upload = hero_field
        try:
            data = await upload.read()
            if data and len(data) > 0:
                loc, og_w, og_h = await save_blog_editor_image(data, upload.filename or "hero.jpg")
                hero_url = loc
        except ValueError as e:
            _flash(request, str(e), "danger")
            dest = f"/admin/blog/editare/{final_slug}" if original_slug else "/admin/blog/nou"
            return RedirectResponse(url=dest, status_code=303)
        except Exception as e:
            log.exception("hero upload")
            _flash(request, f"Eroare imagine hero: {e}", "danger")
            dest = f"/admin/blog/editare/{final_slug}" if original_slug else "/admin/blog/nou"
            return RedirectResponse(url=dest, status_code=303)

    is_edit = bool(original_slug)
    try:
        await admin_upsert_post(
            slug=final_slug,
            title=title,
            excerpt=excerpt,
            content_html=content_html,
            category_id=category_id,
            draft=draft,
            published_at=published_at,
            hero_image_url=hero_url,
            og_image_width=og_w,
            og_image_height=og_h,
            create_new=not is_edit,
        )
    except sqlite3.IntegrityError:
        _flash(
            request,
            "Există deja un articol cu acest slug. Alege alt slug.",
            "danger",
        )
        return RedirectResponse(
            url=f"/admin/blog/editare/{original_slug}" if original_slug else "/admin/blog/nou",
            status_code=303,
        )
    except ValueError as e:
        _flash(request, str(e), "danger")
        return RedirectResponse(
            url=f"/admin/blog/editare/{final_slug}" if original_slug else "/admin/blog/nou",
            status_code=303,
        )

    if is_edit and existing:
        delete_unreferenced_blog_uploads_after_edit(
            existing.hero_image_url,
            existing.content_html,
            hero_url,
            content_html,
        )

    _flash(request, "Articol salvat.", "success")
    return RedirectResponse(url=f"/admin/blog/editare/{final_slug}", status_code=303)


@router.post("/sterge/{slug}")
async def blog_admin_delete(request: Request, slug: str):
    deleted = await admin_delete_post(slug)
    if deleted:
        delete_blog_files_for_post(deleted.hero_image_url, deleted.content_html)
        _flash(request, "Articol șters.", "success")
    else:
        _flash(request, "Nu am găsit articolul.", "warning")
    return RedirectResponse(url="/admin/blog/posts", status_code=303)


@router.post("/upload-image")
async def blog_admin_upload_image(file: UploadFile = File(...)):
    try:
        data = await file.read()
        if not data:
            return JSONResponse({"error": "Fișier gol"}, status_code=400)
        loc, _w, _h = await save_blog_editor_image(data, file.filename or "image.jpg")
        return JSONResponse({"location": loc})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=415)
    except Exception as e:
        log.exception("tinymce upload")
        return JSONResponse({"error": str(e)}, status_code=500)
