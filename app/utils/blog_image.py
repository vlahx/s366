"""
Imagini blog / Open Graph: redimensionare cu Pillow — cea mai lungă latură max 1200px (fără upscale).
Rezultat JPEG; returnează bytes + (lățime, înălțime).
"""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Final

from PIL import Image, ImageFile, ImageOps

logger = logging.getLogger(__name__)

ImageFile.LOAD_TRUNCATED_IMAGES = True

DEFAULT_MAX_LONG_EDGE: Final[int] = 1200
JPEG_QUALITY: Final[int] = 88


def _flatten_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    if img.mode == "P" and "transparency" in img.info:
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    return img.convert("RGB")


def _exif_transpose(img: Image.Image) -> Image.Image:
    try:
        return ImageOps.exif_transpose(img)
    except Exception:
        return img


def resize_image_max_long_edge(
    data: bytes,
    *,
    max_edge: int = DEFAULT_MAX_LONG_EDGE,
    jpeg_quality: int = JPEG_QUALITY,
) -> tuple[bytes, tuple[int, int]]:
    """
    Micșorează păstrând raportul, astfel încât max(lățime, înălțime) <= max_edge.
    Dacă imaginea e deja mai mică, nu o mărește — doar o normalizează în JPEG.
    """
    max_edge = max(64, int(max_edge))
    try:
        with Image.open(BytesIO(data)) as src:
            if getattr(src, "format", None) == "GIF" and getattr(src, "n_frames", 1) > 1:
                # GIF animat: nu procesăm aici
                return data, (src.size[0], src.size[1])
            img = _exif_transpose(src)
            img.load()
            w, h = img.size
            if w < 1 or h < 1:
                raise ValueError("dimensiuni invalide")
            longest = max(w, h)
            if longest > max_edge:
                scale = max_edge / longest
                nw = max(1, int(round(w * scale)))
                nh = max(1, int(round(h * scale)))
                img = img.resize((nw, nh), Image.Resampling.LANCZOS)
            rgb = _flatten_rgb(img)
            buf = BytesIO()
            rgb.save(
                buf,
                format="JPEG",
                quality=jpeg_quality,
                optimize=True,
                progressive=True,
            )
            out = buf.getvalue()
            return out, rgb.size
    except Exception as e:
        logger.warning("blog_image: procesare eșuată (%s)", e)
        raise
