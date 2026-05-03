"""Blog — citire articole și categorii (aiosqlite)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from slugify import slugify

from app.models.sqlite_model import execute_insert, execute_query, fetch_all, fetch_one


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
    author_firstname: str | None
    view_count: int = 0


def _row_author_firstname(r) -> str | None:
    if "author_firstname" not in r.keys():
        return None
    raw = r["author_firstname"]
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _row_view_count(r) -> int:
    if "view_count" not in r.keys():
        return 0
    raw = r["view_count"]
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


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
        author_firstname=_row_author_firstname(r),
        view_count=_row_view_count(r),
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


async def admin_create_category(
    *,
    name: str,
    slug: str | None = None,
    sort_order: int | None = None,
) -> BlogCategory:
    """Inserează categorie nouă. Slug gol → din nume (slugify). sort_order gol → după ultimul +1."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Numele categoriei e obligatoriu")

    raw_slug = (slug or "").strip().lower() if slug else ""
    if not raw_slug:
        raw_slug = slugify(name, lowercase=True) or "categorie"

    if sort_order is None:
        r = await fetch_one("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM blog_categories")
        sort_order = int(r["n"]) if r and r["n"] is not None else 0
    else:
        sort_order = int(sort_order)

    new_id = await execute_insert(
        "INSERT INTO blog_categories (slug, name, sort_order) VALUES (?, ?, ?)",
        (raw_slug, name, sort_order),
    )
    r = await fetch_one(
        "SELECT id, slug, name, sort_order FROM blog_categories WHERE id = ?",
        (int(new_id),),
    )
    if not r:
        raise RuntimeError("Categoria nu s-a putut citi după inserare")
    return BlogCategory(
        id=int(r["id"]),
        slug=str(r["slug"]),
        name=str(r["name"]),
        sort_order=int(r["sort_order"]),
    )


def _sql_like_pattern(term: str) -> str:
    """Pattern LIKE sigur: escape %, _, \\ pentru SQLite ESCAPE '\\'."""
    t = (term or "").strip()
    if not t:
        return ""
    t = t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


async def list_published_posts(
    *,
    category_slug: str | None = None,
    search: str | None = None,
    limit: int = 100,
) -> list[BlogPostRow]:
    limit = max(1, min(500, int(limit)))
    base_sql = """
        SELECT p.id, p.slug, p.category_id, c.slug AS category_slug, c.name AS category_name,
               p.title, p.excerpt, p.content_html, p.hero_image_url,
               p.og_image_width, p.og_image_height, p.draft, p.published_at, p.created_at,
               p.author_firstname, p.view_count
        FROM blog_posts p
        LEFT JOIN blog_categories c ON c.id = p.category_id
        WHERE p.draft = 0
    """
    conditions: list[str] = []
    params: list = []

    if category_slug:
        conditions.append("c.slug = ?")
        params.append(category_slug.strip().lower())

    like_pat = _sql_like_pattern(search) if search else ""
    if like_pat:
        conditions.append(
            "(p.title LIKE ? ESCAPE '\\' OR IFNULL(p.excerpt, '') LIKE ? ESCAPE '\\')"
        )
        params.extend([like_pat, like_pat])

    tail = " ORDER BY COALESCE(p.published_at, p.created_at) DESC LIMIT ?"
    if conditions:
        sql = base_sql + " AND " + " AND ".join(conditions) + tail
    else:
        sql = base_sql + tail
    params.append(limit)
    rows = await fetch_all(sql, tuple(params))
    return [_row_post(r) for r in rows]


async def get_published_post_by_slug(slug: str) -> BlogPostRow | None:
    slug = (slug or "").strip().lower()
    if not slug:
        return None
    r = await fetch_one(
        """
        SELECT p.id, p.slug, p.category_id, c.slug AS category_slug, c.name AS category_name,
               p.title, p.excerpt, p.content_html, p.hero_image_url,
               p.og_image_width, p.og_image_height, p.draft, p.published_at, p.created_at,
               p.author_firstname, p.view_count
        FROM blog_posts p
        LEFT JOIN blog_categories c ON c.id = p.category_id
        WHERE p.slug = ? AND p.draft = 0
        """,
        (slug,),
    )
    return _row_post(r) if r else None


async def increment_blog_post_view_count(slug: str) -> int:
    """Incrementează vizualizările unui articol publicat; returnează valoarea după increment."""
    slug = (slug or "").strip().lower()
    if not slug:
        return 0
    await execute_query(
        """
        UPDATE blog_posts
        SET view_count = COALESCE(view_count, 0) + 1
        WHERE slug = ? AND draft = 0
        """,
        (slug,),
    )
    r = await fetch_one(
        "SELECT view_count FROM blog_posts WHERE slug = ? AND draft = 0",
        (slug,),
    )
    return _row_view_count(r) if r else 0


async def increment_listing_page_views(page_key: str) -> int:
    """
    Contor pentru pagini listă (ex. blog:index, blog:category:ghiduri).
    """
    key = (page_key or "").strip()
    if not key or len(key) > 200:
        return 0
    await execute_query(
        """
        INSERT INTO page_views (page_key, view_count) VALUES (?, 1)
        ON CONFLICT(page_key) DO UPDATE SET view_count = view_count + 1
        """,
        (key,),
    )
    r = await fetch_one(
        "SELECT view_count FROM page_views WHERE page_key = ?",
        (key,),
    )
    return int(r["view_count"]) if r and r["view_count"] is not None else 0


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
               p.og_image_width, p.og_image_height, p.draft, p.published_at, p.created_at,
               p.author_firstname, p.view_count
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
               p.og_image_width, p.og_image_height, p.draft, p.published_at, p.created_at,
               p.author_firstname, p.view_count
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
    author_firstname: str | None = None,
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
        af_up = (author_firstname or "").strip() or None
        await execute_query(
            """
            UPDATE blog_posts SET
                category_id = ?, title = ?, excerpt = ?, content_html = ?,
                hero_image_url = ?, og_image_width = ?, og_image_height = ?,
                draft = ?, published_at = ?, updated_at = datetime('now'),
                author_firstname = COALESCE(author_firstname, ?)
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
                af_up,
                slug,
            ),
        )
        return slug

    if not create_new:
        raise ValueError("Articolul nu mai există (slug șters sau invalid).")

    af = (author_firstname or "").strip() or None
    await execute_query(
        """
        INSERT INTO blog_posts (
            slug, category_id, title, excerpt, content_html,
            hero_image_url, og_image_width, og_image_height,
            draft, published_at, created_at, updated_at, author_firstname
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?)
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
            af,
        ),
    )
    return slug
