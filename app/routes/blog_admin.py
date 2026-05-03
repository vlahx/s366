# Admin blog — doar superadmin (Depends pe router)
from __future__ import annotations

import asyncio
import csv
import io
import logging
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pathlib import Path
from slugify import slugify
from starlette.concurrency import run_in_threadpool

from app.utils.blog_db import (
    admin_blog_approve_comment,
    admin_blog_list_pending_comments,
    admin_blog_newsletter_subscribers,
    admin_blog_newsletter_active_for_send,
    admin_blog_reject_comment,
    admin_create_category,
    admin_delete_post,
    admin_get_post_by_slug,
    admin_list_all_posts,
    admin_upsert_post,
    list_categories,
)
from app.utils.blog_newsletter_automation import schedule_blog_post_newsletter_broadcast
from app.utils.blog_newsletter_mail import (
    build_unsubscribe_url,
    newsletter_mail_configured,
    send_newsletter_email,
)
from app.utils.ip_isp_hint import is_likely_digi_rcs
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


@router.get("/categorii")
async def blog_admin_categories(request: Request):
    cats = await list_categories()
    return templates.TemplateResponse(
        request=request,
        name="admin/blog_categories.html",
        context={"request": request, "categories": cats, "title": "Categorii blog — S366 AI (admin)"},
    )


@router.post("/categorii/nou")
async def blog_admin_category_create(request: Request):
    form = await request.form()
    name = (form.get("name") or "").strip()
    slug_in = (form.get("slug") or "").strip().lower() or None
    so_raw = form.get("sort_order")
    sort_order: int | None = None
    if so_raw not in (None, ""):
        try:
            sort_order = int(so_raw)
        except (TypeError, ValueError):
            sort_order = None
    try:
        await admin_create_category(name=name, slug=slug_in, sort_order=sort_order)
    except sqlite3.IntegrityError:
        _flash(request, "Există deja o categorie cu acest slug. Alege alt slug sau nume.", "danger")
        return RedirectResponse(url="/admin/blog/categorii", status_code=303)
    except ValueError as e:
        _flash(request, str(e), "danger")
        return RedirectResponse(url="/admin/blog/categorii", status_code=303)
    _flash(request, "Categorie creată.", "success")
    return RedirectResponse(url="/admin/blog/categorii", status_code=303)


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
    newsletter_on_publish = form.get("newsletter_on_publish") == "on"
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
    author_fn = (request.session.get("firstname") or "").strip() or None
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
            author_firstname=author_fn,
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

    post_after = await admin_get_post_by_slug(final_slug)
    transition = not draft and (existing is None or existing.draft)
    retry_newsletter = bool(
        existing
        and not existing.draft
        and not draft
        and post_after
        and post_after.newsletter_sent_at is None
    )
    should_newsletter = (
        newsletter_on_publish
        and newsletter_mail_configured()
        and post_after
        and not post_after.draft
        and post_after.newsletter_sent_at is None
        and (transition or retry_newsletter)
    )
    if should_newsletter:
        asyncio.create_task(schedule_blog_post_newsletter_broadcast(final_slug))
        _flash(
            request,
            "Articol salvat. Newsletter-ul se trimite în fundal, pe grupe mici de abonați.",
            "success",
        )
    else:
        if newsletter_on_publish and not newsletter_mail_configured():
            _flash(
                request,
                "Articol salvat. Newsletter bifat, dar SMTP newsletter (NEWSLETTER_*) nu e configurat — nu s-a trimis.",
                "warning",
            )
        elif newsletter_on_publish and post_after and post_after.newsletter_sent_at is not None:
            _flash(request, "Articol salvat. Newsletter deja trimis pentru acest articol.", "success")
        else:
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


@router.get("/moderare-comentarii")
async def blog_admin_moderation_comments(request: Request):
    pending = await admin_blog_list_pending_comments()
    pending_display = [
        {**asdict(r), "is_digi": is_likely_digi_rcs(r.submitter_ip)}
        for r in pending
    ]
    return templates.TemplateResponse(
        request=request,
        name="admin/blog_moderation.html",
        context={
            "request": request,
            "pending": pending_display,
            "title": "Moderare comentarii blog — S366 AI",
        },
    )


@router.post("/moderare-comentarii/aproba/{rating_id}")
async def blog_admin_moderation_approve(request: Request, rating_id: int):
    if await admin_blog_approve_comment(rating_id):
        _flash(request, "Comentariu aprobat pentru afișare publică.", "success")
    else:
        _flash(request, "Înregistrarea nu mai era în așteptare.", "warning")
    return RedirectResponse(url="/admin/blog/moderare-comentarii", status_code=303)


@router.post("/moderare-comentarii/respinge/{rating_id}")
async def blog_admin_moderation_reject(request: Request, rating_id: int):
    if await admin_blog_reject_comment(rating_id):
        _flash(request, "Comentariu respins (nu va apărea public).", "success")
    else:
        _flash(request, "Înregistrarea nu mai era în așteptare.", "warning")
    return RedirectResponse(url="/admin/blog/moderare-comentarii", status_code=303)


@router.get("/newsletter")
async def blog_admin_newsletter(request: Request):
    subscribers = await admin_blog_newsletter_subscribers()
    smtp_ok = newsletter_mail_configured()
    return templates.TemplateResponse(
        request=request,
        name="admin/blog_newsletter.html",
        context={
            "request": request,
            "subscribers": subscribers,
            "smtp_configured": smtp_ok,
            "title": "Newsletter blog — S366 AI",
        },
    )


@router.get("/newsletter/export.csv")
async def blog_admin_newsletter_export_csv():
    rows = await admin_blog_newsletter_subscribers()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email", "active", "created_at", "unsub_token"])
    for r in rows:
        w.writerow(
            [
                r.email,
                r.active,
                r.created_at.isoformat() if r.created_at else "",
                r.unsub_token,
            ]
        )
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="blog-newsletter.csv"',
        },
    )


def _send_newsletter_batch(subject: str, html_body: str, pairs: list[tuple[str, str]]) -> tuple[int, int]:
    ok, fail = 0, 0
    for email, token in pairs:
        try:
            footer = (
                f'<p style="font-size:12px;color:#666;"><a href="'
                f'{build_unsubscribe_url(token)}">Dezabonare newsletter</a></p>'
            )
            send_newsletter_email(
                to_email=email,
                subject=subject,
                html_body=html_body + footer,
                unsub_token=token,
            )
            ok += 1
        except Exception:
            log.exception("newsletter send to %s", email)
            fail += 1
    return ok, fail


@router.post("/newsletter/trimite")
async def blog_admin_newsletter_send(request: Request):
    form = await request.form()
    subject = (form.get("subject") or "").strip()
    html_body = (form.get("html_body") or "").strip()
    if not subject or not html_body:
        _flash(request, "Completează subiectul și conținutul HTML.", "danger")
        return RedirectResponse(url="/admin/blog/newsletter", status_code=303)
    if not newsletter_mail_configured():
        _flash(
            request,
            "SMTP newsletter neconfigurat. Setează NEWSLETTER_SMTP_HOST, NEWSLETTER_FROM_EMAIL etc.",
            "warning",
        )
        return RedirectResponse(url="/admin/blog/newsletter", status_code=303)
    pairs = await admin_blog_newsletter_active_for_send()
    if not pairs:
        _flash(request, "Nu există abonați activi.", "warning")
        return RedirectResponse(url="/admin/blog/newsletter", status_code=303)
    ok, fail = await run_in_threadpool(
        _send_newsletter_batch, subject, html_body, pairs
    )
    if fail == 0:
        _flash(request, f"Newsletter trimis către {ok} adrese.", "success")
    else:
        _flash(
            request,
            f"Trimise cu succes: {ok}, eșuate: {fail}. Verifică logurile.",
            "warning",
        )
    return RedirectResponse(url="/admin/blog/newsletter", status_code=303)
