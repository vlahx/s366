# Blog public — articole și categorii
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.utils.blog_db import (
    blog_newsletter_subscribe,
    blog_newsletter_unsubscribe,
    blog_post_approved_comments,
    blog_post_rating_summary,
    blog_post_submit_rating,
    blog_rating_ip_hash,
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
BLOG_LISTING_OG_STATIC_PATH = "/static/images/og/blog-list.png"
BLOG_LISTING_OG_WIDTH = 1376
BLOG_LISTING_OG_HEIGHT = 768


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _norm_search(q: str | None) -> str | None:
    s = (q or "").strip()
    return s if s else None


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return ""


def _safe_blog_redirect_base(referer: str | None) -> str:
    if not referer:
        return "/blog/"
    try:
        p = urlparse(referer)
        path = p.path or "/blog/"
        if not path.startswith("/blog"):
            return "/blog/"
        q = f"?{p.query}" if p.query else ""
        return f"{path}{q}"
    except Exception:
        return "/blog/"


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
            "og_image_width": BLOG_LISTING_OG_WIDTH,
            "og_image_height": BLOG_LISTING_OG_HEIGHT,
            "seo_og_url": canonical_blog,
            "canonical_blog": canonical_blog,
            "seo_og_image_abs": f"{origin}{BLOG_LISTING_OG_STATIC_PATH}",
            "seo_og_image_alt": "S366 AI Blog — articole despre AI pentru firme",
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


@router.post("/newsletter/subscribe")
async def blog_newsletter_subscribe_route(
    request: Request,
    email: str = Form(""),
    url: str = Form(""),  # honeypot — lăsat gol de oameni
):
    if (url or "").strip():
        return RedirectResponse(url="/blog/", status_code=303)
    result = await blog_newsletter_subscribe(email)
    q = "newsletter=ok" if result == "ok" else "newsletter=invalid"
    base = _safe_blog_redirect_base(request.headers.get("referer"))
    sep = "&" if "?" in base else "?"
    return RedirectResponse(url=f"{base}{sep}{q}", status_code=303)


@router.get("/newsletter/unsubscribe", response_class=HTMLResponse)
async def blog_newsletter_unsubscribe_route(request: Request, token: str = ""):
    ok = await blog_newsletter_unsubscribe(token)
    return templates.TemplateResponse(
        request=request,
        name="blog/newsletter_unsubscribe.html",
        context={"request": request, "ok": ok},
    )


@router.post("/feedback")
async def blog_post_feedback_route(
    request: Request,
    post_slug: str = Form(...),
    stars: int = Form(...),
    comment: str = Form(""),
    url: str = Form(""),  # honeypot
):
    if (url or "").strip():
        slug = (post_slug or "").strip().lower()
        return RedirectResponse(url=f"/blog/{slug}/", status_code=303)
    ip = _client_ip(request)
    ih = blog_rating_ip_hash(ip, post_slug)
    result = await blog_post_submit_rating(post_slug, stars, comment, ih, _client_ip(request))
    slug = (post_slug or "").strip().lower()
    tail = "rating=ok" if result == "ok" else "rating=err"
    return RedirectResponse(url=f"/blog/{slug}/?{tail}", status_code=303)


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
    rating_summary = await blog_post_rating_summary(post.slug)
    approved_comments = await blog_post_approved_comments(post.slug)
    return templates.TemplateResponse(
        request=request,
        name="blog/post.html",
        context={
            "request": request,
            "post": post,
            "article_view_count": article_view_count,
            "rating_summary": rating_summary,
            "approved_comments": approved_comments,
            "meta_description": og.description,
            "og_image_width": og.image_width,
            "og_image_height": og.image_height,
            "og_is_card": og.is_default_card,
            "canonical_url": canonical,
            "published_utc": pub,
            "share_url": canonical,
            "seo_og_url": canonical,
            "seo_og_image_abs": og.image_abs,
            "seo_og_image_alt": post.title,
        },
    )


@router.get("/{post_slug}/", response_class=HTMLResponse, name="blog_post")
async def blog_post_trailing_slash(request: Request, post_slug: str):
    return await _blog_post_page(request, post_slug)


@router.get("/{post_slug}", response_class=HTMLResponse, name="blog_post_legacy")
async def blog_post_no_trailing_slash(request: Request, post_slug: str):
    """
    Aceeași pagină ca /blog/{slug}/ — fără 308.
    Crawleri (ex. facebookexternalhit) adesea nu urmează redirectul și rămân fără HTML/OG.
    """
    return await _blog_post_page(request, post_slug)
