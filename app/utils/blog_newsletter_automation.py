"""
Newsletter automat la publicarea unui articol — trimitere în fundal, pe loturi mici (anti-spam).
Env: NEWSLETTER_BATCH_SIZE (default 15), NEWSLETTER_BATCH_PAUSE_SECONDS (default 4).
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.utils.blog_db import (
    admin_blog_newsletter_active_for_send,
    blog_mark_newsletter_sent,
    get_published_post_by_slug,
)
from app.utils.blog_newsletter_mail import (
    build_unsubscribe_url,
    newsletter_mail_configured,
    send_newsletter_email,
)
from app.utils.blog_og import canonical_image_url, site_origin

log = logging.getLogger(__name__)


def _templates_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "templates"


def render_new_post_newsletter_html(*, post, origin: str, unsub_url: str) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_templates_dir())),
        autoescape=select_autoescape(["html", "xml"]),
    )
    hero_abs = None
    if post.hero_image_url:
        hero_abs = canonical_image_url(origin, post.hero_image_url)
    post_url = f"{origin.rstrip('/')}/blog/{post.slug}/"
    tpl = env.get_template("email/blog_new_post.html")
    return tpl.render(
        post=post,
        origin=origin,
        hero_abs=hero_abs,
        post_url=post_url,
        unsub_url=unsub_url,
    )


async def run_blog_post_newsletter_broadcast(slug: str) -> None:
    slug = (slug or "").strip().lower()
    if not slug or not newsletter_mail_configured():
        return
    post = await get_published_post_by_slug(slug)
    if not post or post.draft or post.newsletter_sent_at is not None:
        return
    origin = (os.environ.get("NEWSLETTER_PUBLIC_ORIGIN") or "https://s366.online").rstrip("/")
    pairs = await admin_blog_newsletter_active_for_send()
    if not pairs:
        log.info("newsletter broadcast: no active subscribers for %s", slug)
        await blog_mark_newsletter_sent(slug)
        return
    batch_size = max(1, int(os.environ.get("NEWSLETTER_BATCH_SIZE") or "15"))
    pause = max(0.5, float(os.environ.get("NEWSLETTER_BATCH_PAUSE_SECONDS") or "4"))
    subject = f"Nou pe blog: {post.title}"
    subject = subject[:200] if len(subject) > 200 else subject
    failed = 0
    for i in range(0, len(pairs), batch_size):
        chunk = pairs[i : i + batch_size]
        for email, token in chunk:
            unsub = build_unsubscribe_url(token)
            try:
                html_body = await asyncio.to_thread(
                    lambda: render_new_post_newsletter_html(
                        post=post, origin=origin, unsub_url=unsub
                    )
                )
                await asyncio.to_thread(
                    lambda: send_newsletter_email(
                        to_email=email,
                        subject=subject,
                        html_body=html_body,
                        unsub_token=token,
                    )
                )
            except Exception:
                log.exception("newsletter broadcast fail slug=%s to=%s", slug, email)
                failed += 1
        if i + batch_size < len(pairs):
            await asyncio.sleep(pause)
    if failed == 0:
        await blog_mark_newsletter_sent(slug)
        log.info("newsletter broadcast ok slug=%s count=%s", slug, len(pairs))
    else:
        log.warning(
            "newsletter broadcast partial slug=%s failed=%s total=%s (newsletter_sent_at nemarcat)",
            slug,
            failed,
            len(pairs),
        )


async def schedule_blog_post_newsletter_broadcast(slug: str) -> None:
    try:
        await run_blog_post_newsletter_broadcast(slug)
    except Exception:
        log.exception("newsletter broadcast crashed slug=%s", slug)
