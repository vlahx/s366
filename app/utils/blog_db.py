"""Blog — citire articole și categorii (aiosqlite)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.sqlite_model import execute_query, fetch_all, fetch_one


def _sqlite_datetime(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class BlogCategory:
    id: int
    slug: str
    name: str
    sort_order: int


@dataclass(frozen=True)
class BlogPostRow:
    id: int
    slug: str
    category_id: int | None
    category_slug: str | None
    category_name: str | None
    title: str
    excerpt: str | None
    content_html: str
    hero_image_url: str | None
    og_image_width: int | None
    og_image_height: int | None
    draft: bool
    published_at: datetime | None
    created_at: datetime | None


def _row_post(r) -> BlogPostRow:
    def _dt(v) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))

    return BlogPostRow(
        id=int(r["id"]),
        slug=str(r["slug"]),
        category_id=int(r["category_id"]) if r["category_id"] is not None else None,
        category_slug=str(r["category_slug"]) if r["category_slug"] is not None else None,
        category_name=str(r["category_name"]) if r["category_name"] is not None else None,
        title=str(r["title"]),
        excerpt=str(r["excerpt"]) if r["excerpt"] is not None else None,
        content_html=str(r["content_html"] or ""),
        hero_image_url=str(r["hero_image_url"]) if r["hero_image_url"] is not None else None,
        og_image_width=int(r["og_image_width"]) if r["og_image_width"] is not None else None,
        og_image_height=int(r["og_image_height"]) if r["og_image_height"] is not None else None,
        draft=bool(r["draft"]),
        published_at=_dt(r["published_at"]),
        created_at=_dt(r["created_at"]),
    )


async def list_categories() -> list[BlogCategory]:
    rows = await fetch_all(
        "SELECT id, slug, name, sort_order FROM blog_categories ORDER BY sort_order ASC, name ASC"
    )
    return [
        BlogCategory(
            id=int(r["id"]),
            slug=str(r["slug"]),
            name=str(r["name"]),
            sort_order=int(r["sort_order"]),
        )
        for r in rows
    ]


async def list_published_posts(
    *,
    category_slug: str | None = None,
    limit: int = 100,
) -> list[BlogPostRow]:
    limit = max(1, min(500, int(limit)))
    base_sql = """
        SELECT p.id, p.slug, p.category_id, c.slug AS category_slug, c.name AS category_name,
               p.title, p.excerpt, p.content_html, p.hero_image_url,
               p.og_image_width, p.og_image_height, p.draft, p.published_at, p.created_at
        FROM blog_posts p
        LEFT JOIN blog_categories c ON c.id = p.category_id
        WHERE p.draft = 0
    """
    if category_slug:
        rows = await fetch_all(
            base_sql + " AND c.slug = ? ORDER BY COALESCE(p.published_at, p.created_at) DESC LIMIT ?",
            (category_slug.strip().lower(), limit),
        )
    else:
        rows = await fetch_all(
            base_sql + " ORDER BY COALESCE(p.published_at, p.created_at) DESC LIMIT ?",
            (limit,),
        )
    return [_row_post(r) for r in rows]


async def get_published_post_by_slug(slug: str) -> BlogPostRow | None:
    slug = (slug or "").strip().lower()
    if not slug:
        return None
    r = await fetch_one(
        """
        SELECT p.id, p.slug, p.category_id, c.slug AS category_slug, c.name AS category_name,
               p.title, p.excerpt, p.content_html, p.hero_image_url,
               p.og_image_width, p.og_image_height, p.draft, p.published_at, p.created_at
        FROM blog_posts p
        LEFT JOIN blog_categories c ON c.id = p.category_id
        WHERE p.slug = ? AND p.draft = 0
        """,
        (slug,),
    )
    return _row_post(r) if r else None


async def list_published_slugs_for_sitemap() -> list[str]:
    rows = await fetch_all(
        """
        SELECT slug FROM blog_posts
        WHERE draft = 0
        ORDER BY COALESCE(published_at, created_at) DESC
        """
    )
    return [str(r["slug"]) for r in rows]


async def admin_list_all_posts() -> list[BlogPostRow]:
    rows = await fetch_all(
        """
        SELECT p.id, p.slug, p.category_id, c.slug AS category_slug, c.name AS category_name,
               p.title, p.excerpt, p.content_html, p.hero_image_url,
               p.og_image_width, p.og_image_height, p.draft, p.published_at, p.created_at
        FROM blog_posts p
        LEFT JOIN blog_categories c ON c.id = p.category_id
        ORDER BY COALESCE(p.updated_at, p.created_at) DESC, p.id DESC
        """
    )
    return [_row_post(r) for r in rows]


async def admin_get_post_by_slug(slug: str) -> BlogPostRow | None:
    slug = (slug or "").strip().lower()
    if not slug:
        return None
    r = await fetch_one(
        """
        SELECT p.id, p.slug, p.category_id, c.slug AS category_slug, c.name AS category_name,
               p.title, p.excerpt, p.content_html, p.hero_image_url,
               p.og_image_width, p.og_image_height, p.draft, p.published_at, p.created_at
        FROM blog_posts p
        LEFT JOIN blog_categories c ON c.id = p.category_id
        WHERE p.slug = ?
        """,
        (slug,),
    )
    return _row_post(r) if r else None


async def admin_delete_post(slug: str) -> BlogPostRow | None:
    """Șterge articolul din DB; returnează rândul șters pentru curățare fișiere pe disc."""
    slug = (slug or "").strip().lower()
    if not slug:
        return None
    post = await admin_get_post_by_slug(slug)
    if not post:
        return None
    await execute_query("DELETE FROM blog_posts WHERE slug = ?", (slug,))
    return post


async def admin_upsert_post(
    *,
    slug: str,
    title: str,
    excerpt: str,
    content_html: str,
    category_id: int | None,
    draft: bool,
    published_at: datetime | None,
    hero_image_url: str | None,
    og_image_width: int | None,
    og_image_height: int | None,
    create_new: bool = False,
) -> str:
    """INSERT sau UPDATE după slug. Returnează slugul final.
    Dacă create_new=True și slugul există deja, ridică ValueError (nu suprascrie)."""
    slug = (slug or "").strip().lower()
    title = (title or "").strip()
    if not title:
        raise ValueError("Titlul e obligatoriu")
    if not slug:
        raise ValueError("Slug invalid")

    excerpt = (excerpt or "").strip()
    content_html = (content_html or "").strip()
    d_int = 1 if draft else 0

    pub_sql = _sqlite_datetime(published_at)

    existing = await fetch_one("SELECT id FROM blog_posts WHERE slug = ?", (slug,))

    if existing:
        if create_new:
            raise ValueError("Există deja un articol cu acest slug. Alege alt slug.")
        await execute_query(
            """
            UPDATE blog_posts SET
                category_id = ?, title = ?, excerpt = ?, content_html = ?,
                hero_image_url = ?, og_image_width = ?, og_image_height = ?,
                draft = ?, published_at = ?, updated_at = datetime('now')
            WHERE slug = ?
            """,
            (
                category_id,
                title,
                excerpt,
                content_html,
                hero_image_url,
                og_image_width,
                og_image_height,
                d_int,
                pub_sql,
                slug,
            ),
        )
        return slug

    if not create_new:
        raise ValueError("Articolul nu mai există (slug șters sau invalid).")

    await execute_query(
        """
        INSERT INTO blog_posts (
            slug, category_id, title, excerpt, content_html,
            hero_image_url, og_image_width, og_image_height,
            draft, published_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            slug,
            category_id,
            title,
            excerpt,
            content_html,
            hero_image_url,
            og_image_width,
            og_image_height,
            d_int,
            pub_sql,
        ),
    )
    return slug
