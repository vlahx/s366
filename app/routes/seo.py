# SEO: sitemap dinamic + robots.txt
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from app.utils.sitemap_build import (
    build_robots_txt,
    build_sitemap_xml,
    default_public_entries,
    dynamic_entries,
    site_origin,
)

router = APIRouter(tags=["SEO"])


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(request: Request):
    base = str(request.base_url).rstrip("/")
    origin = site_origin(base)
    static_list = default_public_entries()
    extra = await dynamic_entries()
    # dedupe by path (dynamic poate suprascrie prioritatea dacă vrei — aici punem dynamic după)
    seen: set[str] = set()
    merged = []
    for e in static_list + extra:
        if e.path in seen:
            continue
        seen.add(e.path)
        merged.append(e)
    xml = build_sitemap_xml(origin, merged)
    return Response(content=xml, media_type="application/xml; charset=utf-8")


@router.get("/robots.txt", include_in_schema=False)
async def robots_txt(request: Request):
    base = str(request.base_url).rstrip("/")
    origin = site_origin(base)
    return PlainTextResponse(build_robots_txt(origin), media_type="text/plain; charset=utf-8")
