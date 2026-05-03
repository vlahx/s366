# Blog public — articole și categorii
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.utils.blog_db import (
    count_published_posts,
    get_published_post_by_slug,
    increment_blog_post_view_count,
    increment_listing_page_views,
    list_categories,
    list_published_posts,
)
from app.utils.blog_og import build_post_og, published_utc, site_origin

router = APIRouter()
_templates_dir = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

BLOG_INDEX_PAGE_SIZE = 6


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _norm_search(q: str | None) -> str | None:
    s = (q or "").strip()
    return s if s else None


def _blog_list_query_string(*, page: int, search: str | None) -> str:
    qd: dict[str, str] = {}
    if page > 1:
        qd["page"] = str(page)
    if search:
        qd["q"] = search
    return f"?{urlencode(qd)}" if qd else ""


async def _render_blog_index(
    request: Request,
    category_slug: str | None,
    *,
    search: str | None = None,
    page: int = 1,
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

    total_posts = await count_published_posts(category_slug=category_slug, search=search)
    total_pages = max(1, (total_posts + BLOG_INDEX_PAGE_SIZE - 1) // BLOG_INDEX_PAGE_SIZE)
    page = max(1, page)
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * BLOG_INDEX_PAGE_SIZE

    posts = await list_published_posts(
        category_slug=category_slug,
        search=search,
        limit=BLOG_INDEX_PAGE_SIZE,
        offset=offset,
    )
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
    list_path = (
        f"{origin}/blog/"
        if not category_slug
        else f"{origin}/blog/category/{category_slug}/"
    )
    canonical_blog = list_path.rstrip("/") + "/" + _blog_list_query_string(page=page, search=search)
    blog_list_href_base = (
        "/blog/" if not category_slug else f"/blog/category/{category_slug}/"
    )
    list_page_key = (
        f"blog:category:{category_slug}" if category_slug else "blog:index"
    )
    listing_view_count = await increment_listing_page_views(list_page_key)

    page_nums: list[int] = []
    if total_pages <= 7:
        page_nums = list(range(1, total_pages + 1))
    else:
        want = {1, total_pages, page, page - 1, page + 1, page - 2, page + 2}
        ordered = sorted(p for p in want if 1 <= p <= total_pages)
        prev = 0
        for p in ordered:
            if prev and p > prev + 1:
                page_nums.append(0)
            page_nums.append(p)
            prev = p

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
            "listing_view_count": listing_view_count,
            "blog_page": page,
            "blog_total_pages": total_pages,
            "blog_total_posts": total_posts,
            "blog_page_size": BLOG_INDEX_PAGE_SIZE,
            "blog_page_nums": page_nums,
            "blog_list_href_base": blog_list_href_base,
            "blog_search_q": search,
            "blog_query_suffix": _blog_list_query_string,
            "meta_description": idx_og.description,
            "og_image_width": idx_og.image_width,
            "og_image_height": idx_og.image_height,
            "seo_og_url": canonical_blog,
            "canonical_blog": canonical_blog,
            "seo_og_image_abs": idx_og.image_abs,
        },
    )


@router.get("/", response_class=HTMLResponse, name="blog_index")
async def blog_index(
    request: Request,
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1, le=10_000),
):
    return await _render_blog_index(request, None, search=_norm_search(q), page=page)


@router.get("/category/{cat_slug}", response_class=HTMLResponse, name="blog_category")
async def blog_category(
    request: Request,
    cat_slug: str,
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1, le=10_000),
):
    return await _render_blog_index(
        request, cat_slug.strip().lower(), search=_norm_search(q), page=page
    )


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
    article_view_count = await increment_blog_post_view_count(post.slug)
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
            "article_view_count": article_view_count,
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
