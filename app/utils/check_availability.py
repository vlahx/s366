from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import asyncio
from typing import Any, Optional

import dns.resolver
import httpx


_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}\Z)(?!-)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z",
    re.IGNORECASE,
)


def normalize_domain(raw: str) -> str:
    s = (raw or "").strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0]
    s = s.split("?")[0]
    s = s.split("#")[0]
    s = s.rstrip(".")
    return s


@dataclass(frozen=True)
class AvailabilityResult:
    domain: str
    available: bool
    status: str
    message: str
    provider: str = "dns-nxdomain"
    details: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "available": self.available,
            "status": self.status,
            "message": self.message,
            "provider": self.provider,
            "details": self.details or {},
        }


def _safe_resolve(
    resolver: dns.resolver.Resolver, domain: str, rrtype: str, *, allow_nxdomain: bool = False
) -> Optional[list[str]]:
    try:
        answers = resolver.resolve(domain, rrtype)
        values: list[str] = []
        for rdata in answers:
            values.append(str(rdata).rstrip("."))
        return values
    except dns.resolver.NXDOMAIN:
        if allow_nxdomain:
            raise
        return None
    except Exception:
        return None


def check_domain_availability_dns(domain: str, *, timeout_s: float = 2.5) -> AvailabilityResult:
    """
    Heuristic availability check:
    - If DNS reports NXDOMAIN -> likely available
    - If it resolves (SOA/NS) -> likely already registered / in use
    """
    normalized = normalize_domain(domain)
    if not normalized:
        return AvailabilityResult(
            domain="",
            available=False,
            status="invalid",
            message="Domeniu lipsă.",
        )

    if not _DOMAIN_RE.match(normalized):
        return AvailabilityResult(
            domain=normalized,
            available=False,
            status="invalid",
            message="Format domeniu invalid. Exemplu: magazin.ro",
        )

    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout_s
    resolver.timeout = timeout_s

    checked_at = datetime.now(timezone.utc).isoformat()

    try:
        # 1) Probe explicit: dacă domeniul NU există, dns-python ridică NXDOMAIN.
        # Folosim NS ca semnal rapid (domain existence / delegation).
        ns = _safe_resolve(resolver, normalized, "NS", allow_nxdomain=True)

        # 2) Colectăm și alte semnale (best-effort) pentru detalii / mod avansat.
        soa = _safe_resolve(resolver, normalized, "SOA")
        a = _safe_resolve(resolver, normalized, "A")
        aaaa = _safe_resolve(resolver, normalized, "AAAA")
        mx = _safe_resolve(resolver, normalized, "MX")

        zone_exists = bool(ns or soa)
        details = {
            "checked_at": checked_at,
            "normalized": normalized,
            "dns": {
                "soa": soa,
                "ns": ns,
                "a": a,
                "aaaa": aaaa,
                "mx": mx,
            },
        }

        if not zone_exists:
            # Dacă nu găsim NS/SOA dar nici NXDOMAIN n-a apărut,
            # domeniul poate exista dar să nu aibă răspuns util (edge cases).
            return AvailabilityResult(
                domain=normalized,
                available=False,
                status="unknown",
                message="Nu am putut confirma starea domeniului. Încearcă din nou.",
                details=details,
            )

        return AvailabilityResult(
            domain=normalized,
            available=False,
            status="taken",
            message="Domeniul pare deja înregistrat (există semnal DNS pentru zonă).",
            details=details,
        )
    except dns.resolver.NXDOMAIN:
        return AvailabilityResult(
            domain=normalized,
            available=True,
            status="available",
            message="Domeniul este disponibil.",
            details={
                "checked_at": checked_at,
                "normalized": normalized,
                "dns": {"nxdomain": True},
            },
        )
    except dns.resolver.Timeout:
        return AvailabilityResult(
            domain=normalized,
            available=False,
            status="error",
            message="Timeout la verificarea DNS. Încearcă din nou.",
            details={"checked_at": checked_at, "normalized": normalized},
        )
    except Exception:
        return AvailabilityResult(
            domain=normalized,
            available=False,
            status="error",
            message="Eroare la verificare. Încearcă din nou.",
            details={"checked_at": checked_at, "normalized": normalized},
        )


def _pick_create_product(payload: dict) -> Optional[dict]:
    products = payload.get("products") or []
    for p in products:
        if (p.get("process") or "create") == "create":
            return p
    return products[0] if products else None


def _split_fqdn_for_hostinger(fqdn: str) -> tuple[str, str] | None:
    """
    Hostinger POST /api/domains/v1/availability cere «domain» fără TLD și «tlds» = ['ro', 'com', ...].
    Pentru FQDN standard «nume.tld» folosim un singur punct (ex. magazin.ro).
    """
    parts = fqdn.rsplit(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1].lower()


def _catalog_item_name_matches_tld(name: str, tld: str) -> bool:
    n = (name or "").strip().lower()
    t = (tld or "").strip().lower()
    if not t:
        return False
    return n == f".{t}" or n.endswith(f".{t}") or f".{t}" in n


def _pick_hostinger_domain_catalog_price(items: list[Any], tld: str) -> Optional[dict[str, Any]]:
    """
    GET /api/billing/v1/catalog — prețuri în cenți. Preferă perioada anuală pentru înregistrare.
    """
    tld = tld.lower().strip()
    matched: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        nm = (item.get("name") or "").strip()
        if _catalog_item_name_matches_tld(nm, tld):
            matched.append(item)

    if not matched:
        if len(items) == 1 and isinstance(items[0], dict):
            matched = [items[0]]
        else:
            return None

    best_item: Optional[dict[str, Any]] = None
    for it in matched:
        nm = (it.get("name") or "").strip().lower()
        if nm == f".{tld}":
            best_item = it
            break
    if best_item is None:
        best_item = matched[0]

    prices = best_item.get("prices") or []
    if not isinstance(prices, list) or not prices:
        return None

    year_prices = [p for p in prices if isinstance(p, dict) and p.get("period_unit") == "year"]
    use_list = year_prices if year_prices else [p for p in prices if isinstance(p, dict)]
    if not use_list:
        return None

    def sort_key(p: dict) -> tuple:
        per = p.get("period") or 1
        cents = p.get("first_period_price")
        if cents is None:
            cents = p.get("price")
        try:
            ic = int(cents) if cents is not None else 10**15
        except (TypeError, ValueError):
            ic = 10**15
        return (0 if per == 1 else 1, ic)

    pick = sorted(use_list, key=sort_key)[0]
    price_cents = pick.get("first_period_price")
    if price_cents is None:
        price_cents = pick.get("price")
    if price_cents is None:
        return None
    try:
        price_cents = int(price_cents)
    except (TypeError, ValueError):
        return None

    cur = (pick.get("currency") or "EUR").upper()
    return {
        "catalog_item_id": best_item.get("id"),
        "catalog_item_name": best_item.get("name"),
        "currency": cur,
        "price_cents": price_cents,
        "first_period_price_cents": pick.get("first_period_price"),
        "period": pick.get("period"),
        "period_unit": pick.get("period_unit"),
    }


async def _fetch_hostinger_domain_catalog_price(
    base: str, token: str, tld: str, timeout_s: float
) -> Optional[dict[str, Any]]:
    """GET /api/billing/v1/catalog?name=.{TLD}* — best-effort; None dacă indisponibil."""
    url = f"{base.rstrip('/')}/api/billing/v1/catalog"
    params = {"name": f".{tld.upper()}*"}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
    except Exception:
        return None

    if resp.status_code != 200:
        return None
    try:
        items = resp.json()
    except Exception:
        return None
    if not isinstance(items, list):
        return None
    picked = _pick_hostinger_domain_catalog_price(items, tld)
    return picked


async def _check_domain_availability_hostinger(
    normalized: str, *, checked_at: str, timeout_s: float
) -> AvailabilityResult | None:
    """
    GET nu există — POST https://developers.hostinger.com/api/domains/v1/availability
    (Bearer token). Rate limit: ~10 cereri/min (doc Hostinger).
    Returnează AvailabilityResult dacă răspunsul e utilizabil; None = încearcă următorul provider.
    """
    token = (
        (os.getenv("HOSTINGER_API_TOKEN") or "").strip()
        or (os.getenv("HOSTINGER_TOKEN") or "").strip()
        or (os.getenv("HOSTINGER_BEARER_TOKEN") or "").strip()
    )
    if not token:
        return None

    split = _split_fqdn_for_hostinger(normalized)
    if not split:
        return None

    sld, tld = split
    base = (os.getenv("HOSTINGER_API_BASE") or "https://developers.hostinger.com").rstrip("/")
    url = f"{base}/api/domains/v1/availability"
    body = {"domain": sld, "tlds": [tld]}

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except Exception:
        return None

    if resp.status_code == 401:
        return AvailabilityResult(
            domain=normalized,
            available=False,
            status="error",
            message="Token Hostinger invalid sau expirat (401). Verifică HOSTINGER_API_TOKEN în mediu.",
            provider="hostinger",
            details={"checked_at": checked_at, "normalized": normalized, "hostinger_http_status": 401},
        )

    if resp.status_code == 429:
        return AvailabilityResult(
            domain=normalized,
            available=False,
            status="error",
            message="Limită Hostinger API atinsă (max. ~10 cereri/min). Încearcă din nou peste un minut.",
            provider="hostinger",
            details={"checked_at": checked_at, "normalized": normalized, "hostinger_http_status": 429},
        )

    if resp.status_code == 422:
        try:
            err = resp.json()
        except Exception:
            err = {}
        return AvailabilityResult(
            domain=normalized,
            available=False,
            status="invalid",
            message="Cerere invalidă către Hostinger (422). Verifică formatul domeniului.",
            provider="hostinger",
            details={"checked_at": checked_at, "normalized": normalized, "hostinger": err},
        )

    if resp.status_code >= 500 or resp.status_code < 200:
        return None

    catalog_price: Optional[dict[str, Any]] = None
    if resp.status_code == 200:
        catalog_price = await _fetch_hostinger_domain_catalog_price(
            base, token, tld, min(timeout_s, 12.0)
        )

    try:
        rows = resp.json()
        if not isinstance(rows, list):
            return None
    except Exception:
        return None

    match = None
    needle = normalized.lower()
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = (row.get("domain") or "").strip().lower()
        if d == needle or d == f"{sld}.{tld}":
            match = row
            break
    if match is None and rows:
        match = rows[0]

    if not match:
        return AvailabilityResult(
            domain=normalized,
            available=False,
            status="unknown",
            message="Hostinger nu a returnat status pentru acest domeniu. Încearcă din nou.",
            provider="hostinger",
            details={"checked_at": checked_at, "normalized": normalized, "hostinger": rows},
        )

    is_available = bool(match.get("is_available"))
    restriction = match.get("restriction")

    hi_details: dict[str, Any] = {"items": rows, "selected": match}
    if catalog_price:
        hi_details["catalog"] = catalog_price

    details: dict = {
        "checked_at": checked_at,
        "normalized": normalized,
        "hostinger": hi_details,
    }

    if is_available:
        msg = "Domeniul este disponibil."
        if restriction:
            msg += f" (atenție: {restriction})"
        return AvailabilityResult(
            domain=normalized,
            available=True,
            status="available",
            message=msg,
            provider="hostinger",
            details=details,
        )

    msg = "Domeniul nu este disponibil pentru înregistrare."
    if restriction:
        msg += f" ({restriction})"
    return AvailabilityResult(
        domain=normalized,
        available=False,
        status="taken",
        message=msg,
        provider="hostinger",
        details=details,
    )


def _extract_best_price(product: dict) -> Optional[dict]:
    prices = product.get("prices") or []
    if not prices:
        return None

    def key(p: dict) -> tuple:
        # Prefer 1 year, then lowest price after taxes
        return (
            0 if (p.get("duration_unit") == "y" and p.get("min_duration") == 1) else 1,
            float(p.get("price_after_taxes") or 10**18),
        )

    best = sorted(prices, key=key)[0]
    return {
        "duration_unit": best.get("duration_unit"),
        "min_duration": best.get("min_duration"),
        "max_duration": best.get("max_duration"),
        "price_after_taxes": best.get("price_after_taxes"),
        "price_before_taxes": best.get("price_before_taxes"),
        "type": best.get("type"),
        "discount": best.get("discount"),
        "normal_price_after_taxes": best.get("normal_price_after_taxes"),
        "normal_price_before_taxes": best.get("normal_price_before_taxes"),
    }


def domain_catalog_gross_cents_from_details(details: dict | None) -> int | None:
    """
    Preț catalog domeniu (TTC / cu taxe incluse în valoarea registrar), în cenți EUR,
    din același `details` returnat de `check_domain_availability`.
    """
    if not details:
        return None
    hi = details.get("hostinger") or {}
    cat = hi.get("catalog") or {}
    pc = cat.get("price_cents")
    if pc is not None:
        try:
            n = int(pc)
            return n if n > 0 else None
        except (TypeError, ValueError):
            pass
    gandi = details.get("gandi") or {}
    bp = gandi.get("best_price") or {}
    pat = bp.get("price_after_taxes")
    if pat is not None:
        try:
            n = int(round(float(pat) * 100))
            return n if n > 0 else None
        except (TypeError, ValueError):
            pass
    return None


async def check_domain_availability(domain: str, *, timeout_s: float = 4.5) -> AvailabilityResult:
    """
    Provider selection:
    - If HOSTINGER_API_TOKEN -> Hostinger POST /api/domains/v1/availability (TLD-uri susținute de ei, ex. .ro)
    - Else if Gandi PAT -> Gandi Domain Check API (disponibilitate + preț)
    - Else -> euristică DNS (best-effort)
    """
    normalized = normalize_domain(domain)
    if not normalized:
        return AvailabilityResult(domain="", available=False, status="invalid", message="Domeniu lipsă.")
    if not _DOMAIN_RE.match(normalized):
        return AvailabilityResult(
            domain=normalized,
            available=False,
            status="invalid",
            message="Format domeniu invalid. Exemplu: magazin.ro",
        )

    checked_at = datetime.now(timezone.utc).isoformat()

    hi = await _check_domain_availability_hostinger(normalized, checked_at=checked_at, timeout_s=min(timeout_s, 15.0))
    if hi is not None:
        return hi

    gandi_pat = os.getenv("GANDI_PAT") or os.getenv("GANDI_API_TOKEN") or os.getenv("GANDI_TOKEN")
    gandi_sharing_id = os.getenv("GANDI_SHARING_ID")
    gandi_currency = os.getenv("GANDI_CURRENCY")  # e.g. EUR
    gandi_country = os.getenv("GANDI_COUNTRY")  # e.g. RO

    if gandi_pat:
        params = [("name", normalized), ("processes", "create")]
        if gandi_currency:
            params.append(("currency", gandi_currency))
        if gandi_country:
            params.append(("country", gandi_country))
        if gandi_sharing_id:
            params.append(("sharing_id", gandi_sharing_id))

        headers = {"Authorization": f"Bearer {gandi_pat}"}
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.get("https://api.gandi.net/v5/domain/check", params=params, headers=headers)
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

            if resp.status_code >= 400:
                # fallback to DNS if Gandi is down/misconfigured
                dns_result = await asyncio.to_thread(check_domain_availability_dns, normalized, timeout_s=2.5)
                return AvailabilityResult(
                    domain=dns_result.domain,
                    available=dns_result.available,
                    status=dns_result.status if dns_result.status != "error" else "unknown",
                    message="Verificare registrar indisponibilă temporar. Am folosit o verificare tehnică (DNS).",
                    provider="gandi+dns",
                    details={
                        "checked_at": checked_at,
                        "normalized": normalized,
                        "gandi_http_status": resp.status_code,
                        "dns": (dns_result.details or {}).get("dns", {}),
                    },
                )

            product = _pick_create_product(data) or {}
            status = product.get("status") or data.get("status") or "error_unknown"
            currency = data.get("currency")
            grid = data.get("grid")
            best_price = _extract_best_price(product) if product else None

            if status in {"available", "available_reserved", "available_preorder"}:
                return AvailabilityResult(
                    domain=normalized,
                    available=True,
                    status="available",
                    message="Domeniul este disponibil.",
                    provider="gandi",
                    details={
                        "checked_at": checked_at,
                        "normalized": normalized,
                        "gandi": {
                            "status": status,
                            "currency": currency,
                            "grid": grid,
                            "best_price": best_price,
                        },
                    },
                )

            if status in {"unavailable", "unavailable_premium", "unavailable_restricted"}:
                return AvailabilityResult(
                    domain=normalized,
                    available=False,
                    status="taken",
                    message="Domeniul este luat.",
                    provider="gandi",
                    details={
                        "checked_at": checked_at,
                        "normalized": normalized,
                        "gandi": {
                            "status": status,
                            "currency": currency,
                            "grid": grid,
                            "best_price": best_price,
                        },
                    },
                )

            if status == "error_invalid":
                return AvailabilityResult(
                    domain=normalized,
                    available=False,
                    status="invalid",
                    message="Format domeniu invalid.",
                    provider="gandi",
                    details={"checked_at": checked_at, "normalized": normalized, "gandi": {"status": status}},
                )

            # pending / timeout / refused / etc.
            return AvailabilityResult(
                domain=normalized,
                available=False,
                status="unknown",
                message="Nu am putut confirma sigur statusul domeniului. Încearcă din nou.",
                provider="gandi",
                details={"checked_at": checked_at, "normalized": normalized, "gandi": {"status": status}},
            )
        except Exception:
            # fallback to DNS
            dns_result = await asyncio.to_thread(check_domain_availability_dns, normalized, timeout_s=2.5)
            return AvailabilityResult(
                domain=dns_result.domain,
                available=dns_result.available,
                status=dns_result.status if dns_result.status != "error" else "unknown",
                message="Verificare registrar indisponibilă temporar. Am folosit o verificare tehnică (DNS).",
                provider="gandi+dns",
                details={
                    "checked_at": checked_at,
                    "normalized": normalized,
                    "dns": (dns_result.details or {}).get("dns", {}),
                },
            )

    # No registrar configured -> DNS heuristic
    return await asyncio.to_thread(check_domain_availability_dns, normalized, timeout_s=2.5)

