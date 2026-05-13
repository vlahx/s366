"""Indicii ISP pentru moderare (ex. RCS&RDS / DIGI) — intervale din env, fără API extern."""
from __future__ import annotations

import ipaddress
import os
from functools import lru_cache
from typing import Union

_Net = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


@lru_cache(maxsize=1)
def _digi_networks() -> tuple[_Net, ...]:
    raw = (os.environ.get("DIGI_IP_CIDRS") or "").strip()
    if not raw:
        return ()
    out: list[_Net] = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(ipaddress.ip_network(p, strict=False))
        except ValueError:
            continue
    return tuple(out)


def is_likely_digi_rcs(ip: str | None) -> bool:
    """
    True dacă IP-ul (IPv4/IPv6) cade într-un CIDR listat în DIGI_IP_CIDRS.
    Exemplu env: DIGI_IP_CIDRS=81.196.0.0/16,86.120.0.0/13
    (întrețineți lista; RCS&RDS folosește multe prefixe — AS8708.)
    """
    if not ip or not (ip := ip.strip()):
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for net in _digi_networks():
        if addr in net:
            return True
    return False
