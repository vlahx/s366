import re
import html
import datetime as dt
from typing import Any

import numpy as np
import httpx
from bs4 import BeautifulSoup

from app.models.sqlite_company_model import get_db
from app.utils.db_rags import embed_text


def _clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    decoded = html.unescape(raw_html)
    soup = BeautifulSoup(decoded, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _make_summary(text: str, max_chars: int = 1200) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) <= max_chars:
        return t
    return t[:max_chars].rstrip() + "…"


async def insert_news_item(
    cui: str,
    *,
    source: str,
    url: str,
    title: str,
    published_at: str | None,
    content_text: str,
    summary_text: str,
    embedding: list[float] | None,
) -> dict[str, Any]:
    conn = await get_db(cui)
    if not conn:
        return {"status": "error", "message": "DB companie indisponibil."}
    try:
        emb_blob = None
        if embedding is not None:
            emb_blob = np.array(embedding, dtype=np.float32).tobytes()

        cur = await conn.execute(
            """
            INSERT OR IGNORE INTO news_items
            (source, url, title, published_at, content_text, summary_text, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                url,
                title or "",
                published_at,
                content_text or "",
                summary_text or "",
                emb_blob,
            ),
        )
        await conn.commit()
        return {
            "status": "success",
            "inserted": 1 if cur.rowcount and cur.rowcount > 0 else 0,
        }
    finally:
        await conn.close()


async def ingest_wordpress_news(
    cui: str,
    *,
    base_url: str,
    max_items: int = 40,
) -> dict[str, Any]:
    """
    MVP ingestion:
    - citește WP REST API /wp-json/wp/v2/posts
    - salvează fiecare postare ca news_item (summary+embedding pe summary)
    """
    b = (base_url or "").strip().rstrip("/")
    if not b:
        return {"status": "error", "message": "base_url este obligatoriu."}

    per_page = min(max(int(max_items), 1), 100)
    api_url = f"{b}/wp-json/wp/v2/posts"
    params = {
        "per_page": per_page,
        "page": 1,
        "_fields": "id,date,title,link,content",
        "orderby": "date",
        "order": "desc",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
        r = await client.get(api_url, params=params)
        if r.status_code >= 400:
            return {"status": "error", "message": f"WP API HTTP {r.status_code}", "api_url": api_url}
        posts = r.json() or []

    inserted = 0
    skipped = 0
    for p in posts[: max_items]:
        url = (p.get("link") or "").strip()
        if not url:
            skipped += 1
            continue
        title = _clean_html(((p.get("title") or {}).get("rendered") or ""))
        content_raw = ((p.get("content") or {}).get("rendered") or "")
        content_text = _clean_html(content_raw)
        if len(content_text) < 200:
            skipped += 1
            continue
        published_at = (p.get("date") or None)

        summary = _make_summary(content_text, 1200)
        emb = embed_text(f"{title}\n\n{summary}")
        res = await insert_news_item(
            cui,
            source="wordpress",
            url=url,
            title=title,
            published_at=published_at,
            content_text=content_text,
            summary_text=summary,
            embedding=emb,
        )
        if res.get("inserted") == 1:
            inserted += 1
        else:
            skipped += 1

    return {
        "status": "success",
        "inserted": inserted,
        "skipped": skipped,
        "source": "wordpress",
        "base_url": b,
    }


async def search_news(
    cui: str,
    *,
    query: str,
    top_k: int = 5,
    days: int = 30,
    threshold: float = 0.35,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"status": "error", "message": "query este obligatoriu."}

    conn = await get_db(cui)
    if not conn:
        return {"status": "error", "message": "DB companie indisponibil."}

    try:
        qv = np.array(embed_text(q), dtype=np.float32)
        norm_q = np.linalg.norm(qv)
        if norm_q <= 0:
            return {"status": "error", "message": "embedding query invalid."}

        where = ""
        params: list[Any] = []
        if days and int(days) > 0:
            since = (dt.datetime.utcnow() - dt.timedelta(days=int(days))).isoformat(timespec="seconds")
            where = "WHERE (published_at IS NULL OR published_at >= ?) "
            params.append(since)

        sql = f"""
            SELECT id, source, url, title, published_at, summary_text, embedding
            FROM news_items
            {where}
            ORDER BY COALESCE(published_at, created_at) DESC
            LIMIT 2000
        """
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()

        results: list[dict[str, Any]] = []
        for r in rows:
            emb_blob = r["embedding"]
            if not emb_blob:
                continue
            db_emb = np.frombuffer(emb_blob, dtype=np.float32)
            # embeddings sunt normalizate (normalize_embeddings=True), dot ≈ cosine
            sim = float(np.dot(qv, db_emb))
            if sim < float(threshold):
                continue
            results.append(
                {
                    "id": r["id"],
                    "source": r["source"],
                    "url": r["url"],
                    "title": r["title"],
                    "published_at": r["published_at"],
                    "summary": r["summary_text"],
                    "score": round(sim, 4),
                }
            )

        results.sort(key=lambda x: x["score"], reverse=True)
        return {"status": "success", "results": results[: int(top_k)]}
    finally:
        await conn.close()

