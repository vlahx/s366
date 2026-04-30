# app/utils/dns_ops.py
import os
import dns.resolver
from typing import Optional  
import logging

logger = logging.getLogger(__name__)

def verify_dns(domain: str, expected_ip: Optional[str] = None) -> dict:
    """
    Verifică dacă domeniul are A record pointing la serverul nostru.
    Returnează dict cu status + detalii pentru frontend.
    """
    if expected_ip is None:
        expected_ip = os.getenv("SERVER_PUBLIC_IP")
        if not expected_ip:
            logger.error("SERVER_PUBLIC_IP not set in environment")
            return {"status": "error", "message": "Server configuration error"}
    
    result = {
        "domain": domain,
        "expected_ip": expected_ip,
        "a_record_found": False,
        "a_record_value": None,
        "valid": False
    }
    
    try:
        answers = dns.resolver.resolve(domain, "A")
        for rdata in answers:
            ip = str(rdata).rstrip(".")
            result["a_record_value"] = ip
            if ip == expected_ip:
                result["a_record_found"] = True
                result["valid"] = True
                logger.info(f"DNS verified for {domain} -> {ip}")
                break
                
    except dns.resolver.NXDOMAIN:
        result["error"] = "Domain does not exist (NXDOMAIN)"
    except dns.resolver.NoAnswer:
        result["error"] = "No A record found for domain"
    except dns.resolver.Timeout:
        result["error"] = "DNS query timeout"
    except Exception as e:
        result["error"] = f"Unexpected error: {str(e)}"
        logger.exception(f"DNS check failed for {domain}")
    
    return result