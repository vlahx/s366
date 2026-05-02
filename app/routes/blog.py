# Blog public — articole și categorii
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.utils.blog_db import get_published_post_by_slug, list_categories, list_published_posts
from app.utils.blog_og import build_post_og, published_utc, site_origin

router = APIRouter()
_templates_dir = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _norm_search(q: str | None) -> str | None:
    s = (q or "").strip()
    return s if s else None


async def _render_blog_index(
    request: Request,
    category_slug: str | None,
    *,
    search: str | None = None,
):
    base = _base(request)
    origin = site_origin(base)
    cats = await list_categories()
    filtered_category_name: str | None = None
    if category_slug:
        for c in cats:
            if c.slug == category_slug:
                filtered_category_name = c.name
                break
        if filtered_category_name is None:
            raise HTTPException(status_code=404, detail="Categorie inexistentă")
    posts = await list_published_posts(category_slug=category_slug, search=search, limit=100)
    posts_view = []
    for p in posts:
        og = build_post_og(
            request_base=base,
            title=p.title,
            excerpt=p.excerpt or "",
            content_html=p.content_html,
            hero_image_url=p.hero_image_url,
            og_image_width=p.og_image_width,
            og_image_height=p.og_image_height,
        )
        posts_view.append({"post": p, "card_image": og.image_abs})
    idx_og = build_post_og(
        request_base=base,
        title="S366 AI Blog",
        excerpt="Noutăți și ghiduri despre AI, automatizare și productivitate pentru firme.",
        content_html="",
        hero_image_url=None,
        og_image_width=None,
        og_image_height=None,
    )
    canonical_blog = (
        f"{origin}/blog/"
        if not category_slug
        else f"{origin}/blog/category/{category_slug}"
    )
    return templates.TemplateResponse(
        request=request,
        name="blog/index.html",
        context={
            "request": request,
            "categories": cats,
            "posts_view": posts_view,
            "active_category": category_slug,
            "filtered_category_name": filtered_category_name,
            "search_query": search or "",
            "meta_description": idx_og.description,
            "og_image_width": idx_og.image_width,
            "og_image_height": idx_og.image_height,
            "seo_og_url": canonical_blog,
            "canonical_blog": canonical_blog,
            "seo_og_image_abs": idx_og.image_abs,
        },
    )


@router.get("/", response_class=HTMLResponse, name="blog_index")
async def blog_index(request: Request, q: str | None = Query(None, max_length=200)):
    return await _render_blog_index(request, None, search=_norm_search(q))


@router.get("/category/{cat_slug}", response_class=HTMLResponse, name="blog_category")
async def blog_category(
    request: Request,
    cat_slug: str,
    q: str | None = Query(None, max_length=200),
):
    return await _render_blog_index(request, cat_slug.strip().lower(), search=_norm_search(q))


async def _blog_post_page(request: Request, post_slug: str):
    if post_slug.lower() in ("category", "api"):
        raise HTTPException(status_code=404)
    base = _base(request)
    origin = site_origin(base)
    post = await get_published_post_by_slug(post_slug)
    if not post:
        return templates.TemplateResponse(
            request=request,
            name="blog/not_found.html",
            context={
                "request": request,
                "slug": post_slug,
            },
            status_code=404,
        )
    og = build_post_og(
        request_base=base,
        title=post.title,
        excerpt=post.excerpt or "",
        content_html=post.content_html,
        hero_image_url=post.hero_image_url,
        og_image_width=post.og_image_width,
        og_image_height=post.og_image_height,
    )
    canonical = f"{origin}/blog/{post.slug}/"
    pub = published_utc(post.published_at, post.created_at)
    return templates.TemplateResponse(
        request=request,
        name="blog/post.html",
        context={
            "request": request,
            "post": post,
            "meta_description": og.description,
            "og_image_width": og.image_width,
            "og_image_height": og.image_height,
            "og_is_card": og.is_default_card,
            "canonical_url": canonical,
            "published_utc": pub,
            "share_url": canonical,
            "seo_og_url": canonical,
            "seo_og_image_abs": og.image_abs,
        },
    )


@router.get("/{post_slug}/", response_class=HTMLResponse, name="blog_post")
async def blog_post_trailing_slash(request: Request, post_slug: str):
    return await _blog_post_page(request, post_slug)


@router.get("/{post_slug}", response_class=HTMLResponse, name="blog_post_legacy")
async def blog_post_redirect_to_slash(post_slug: str):
    """Canonic cu slash final — vechile linkuri fără / primesc 308."""
    return RedirectResponse(url=f"/blog/{post_slug}/", status_code=308)
