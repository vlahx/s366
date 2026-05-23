"""
Extrage blocuri LaTeX înainte de conversia markdown (aceleași reguli ca math_markdown.js).
Folosit la salvare în SQLite ca nl2br / backslash-uri să nu strice \\begin{cases} etc.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Optional

_WS = re.compile(r"\s")


@dataclass(frozen=True)
class _Delim:
    open: str
    close: str
    display: bool
    inline_dollar: bool = False


_DELIMS = (
    _Delim("$$", "$$", True),
    _Delim("$", "$", False, inline_dollar=True),
    _Delim(r"\[", r"\]", True),
    _Delim(r"\(", r"\)", False),
)


def _is_escaped(src: str, idx: int) -> bool:
    return idx > 0 and src[idx - 1] == "\\"


def _is_inline_dollar_open(src: str, idx: int) -> bool:
    if src[idx] != "$" or _is_escaped(src, idx):
        return False
    if idx + 1 < len(src) and src[idx + 1] == "$":
        return False
    if idx + 1 >= len(src):
        return False
    nxt = src[idx + 1]
    if _WS.match(nxt):
        return False
    if nxt.isdigit():
        body_start = idx + 1
        close_idx = _find_inline_dollar_close(src, body_start)
        if close_idx == -1:
            return False
        body = src[body_start:close_idx]
        if re.fullmatch(r"[\d\s.,]+", body):
            return False
        return True
    return True


def _find_inline_dollar_close(src: str, body_start: int) -> int:
    for i in range(body_start, len(src)):
        if src[i] != "$" or _is_escaped(src, i):
            continue
        if i + 1 < len(src) and src[i + 1] == "$":
            continue
        if i > 0 and src[i - 1] == "$":
            continue
        if i > body_start and _WS.match(src[i - 1]):
            continue
        return i
    return -1


def _find_close_index(src: str, body_start: int, spec: _Delim) -> int:
    if spec.inline_dollar:
        return _find_inline_dollar_close(src, body_start)
    return src.find(spec.close, body_start)


def _find_next_delim(src: str, start: int) -> Optional[tuple[int, _Delim]]:
    best_idx = -1
    best: Optional[_Delim] = None
    for d in _DELIMS:
        i = src.find(d.open, start)
        while i != -1:
            if d.inline_dollar and not _is_inline_dollar_open(src, i):
                i = src.find(d.open, i + 1)
                continue
            break
        if i == -1:
            continue
        if best_idx == -1 or i < best_idx:
            best_idx = i
            best = d
        elif i == best_idx and best and len(d.open) > len(best.open):
            best = d
    if best is None:
        return None
    return best_idx, best


def extract_math(md: str) -> tuple[str, list[tuple[str, bool]]]:
    """
    Returnează (text_cu_placeholdere, [(latex, display_mode), ...]).
    Formulele incomplete de la final sunt omise (ca la stream în JS).
    """
    if not md:
        return "", []

    blocks: list[tuple[str, bool]] = []
    out: list[str] = []
    cursor = 0
    while cursor < len(md):
        hit = _find_next_delim(md, cursor)
        if hit is None:
            out.append(md[cursor:])
            break
        idx, spec = hit
        out.append(md[cursor:idx])
        body_start = idx + len(spec.open)
        close_idx = _find_close_index(md, body_start, spec)
        if close_idx == -1:
            break
        latex = md[body_start:close_idx].strip()
        blocks.append((latex, spec.display))
        out.append(_placeholder_html(latex, spec.display))
        cursor = close_idx + len(spec.close)
    return "".join(out), blocks


def _placeholder_html(latex: str, display: bool) -> str:
    esc = html.escape(latex, quote=True)
    flag = "1" if display else "0"
    return f'<span class="katex-pending" data-display="{flag}" data-latex="{esc}"></span>'
