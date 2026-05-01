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


async def check_domain_availability(domain: str, *, timeout_s: float = 4.5) -> AvailabilityResult:
    """
    Provider selection:
    - If Gandi PAT is configured -> use Gandi Domain Check API (authoritative availability + price)
    - Else -> fallback to DNS heuristic (best-effort)
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

    gandi_pat = os.getenv("GANDI_PAT") or os.getenv("GANDI_API_TOKEN") or os.getenv("GANDI_TOKEN")
    gandi_sharing_id = os.getenv("GANDI_SHARING_ID")
    gandi_currency = os.getenv("GANDI_CURRENCY")  # e.g. EUR
    gandi_country = os.getenv("GANDI_COUNTRY")  # e.g. RO

    checked_at = datetime.now(timezone.utc).isoformat()

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

