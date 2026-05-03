"""
Trimitere e-mail newsletter blog — SMTP separat de restul aplicației (variabile NEWSLETTER_*).

Env recomandate:
  NEWSLETTER_SMTP_HOST, NEWSLETTER_SMTP_PORT (default 587)
  NEWSLETTER_SMTP_USER, NEWSLETTER_SMTP_PASSWORD
  NEWSLETTER_FROM_EMAIL — implicit no-reply@s366.online dacă lipsește (creează aliasul la provider)
  NEWSLETTER_FROM_NAME (opțional)
  NEWSLETTER_PUBLIC_ORIGIN — ex. https://s366.online (pentru link dezabonare în HTML)
  NEWSLETTER_SMTP_TLS_VERIFY — implicit „true”. Pune „false” dacă SMTP e intern (ex. hosting_mailserver)
  cu certificat self-signed / CA necunoscută containerului (evită eroarea TLS unknown ca la STARTTLS).
  NEWSLETTER_SMTP_CAFILE — opțional, cale către fișier PEM cu CA-ul serverului SMTP (alternativă la verify=false).

Deliverability: PTR (invers) pentru IP-ul de ieșire ar trebui să fie aliniat cu hostname-ul SMTP (EHLO),
ideal același nume ca în MX (ex. mail.s366.online). Dacă PTR arată alt FQDN, unii furnizori notează
scor mai slab — corectează la host/VPS sau ISP.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


DEFAULT_NEWSLETTER_FROM_EMAIL = "no-reply@s366.online"


def newsletter_mail_configured() -> bool:
    """Doar host SMTP obligatoriu; expeditorul are implicit no-reply@ dacă nu setezi env."""
    return bool((os.environ.get("NEWSLETTER_SMTP_HOST") or "").strip())


def _from_tuple() -> tuple[str, str]:
    raw = (os.environ.get("NEWSLETTER_FROM_EMAIL") or "").strip()
    addr = raw or DEFAULT_NEWSLETTER_FROM_EMAIL
    name = (os.environ.get("NEWSLETTER_FROM_NAME") or "S366 AI Blog").strip()
    return addr, name


def build_unsubscribe_url(unsub_token: str) -> str:
    origin = (os.environ.get("NEWSLETTER_PUBLIC_ORIGIN") or "https://s366.online").rstrip("/")
    return f"{origin}/blog/newsletter/unsubscribe?token={unsub_token}"


def _smtp_tls_context() -> ssl.SSLContext:
    verify_raw = (os.environ.get("NEWSLETTER_SMTP_TLS_VERIFY") or "true").strip().lower()
    insecure = verify_raw in ("0", "false", "no", "off")
    cafile = (os.environ.get("NEWSLETTER_SMTP_CAFILE") or "").strip()
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    ctx = ssl.create_default_context()
    if cafile and os.path.isfile(cafile):
        ctx.load_verify_locations(cafile=cafile)
    return ctx


def send_newsletter_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    unsub_token: str | None = None,
) -> None:
    if not newsletter_mail_configured():
        raise RuntimeError("NEWSLETTER_SMTP_HOST nu este setat.")
    host = (os.environ.get("NEWSLETTER_SMTP_HOST") or "").strip()
    port = int(os.environ.get("NEWSLETTER_SMTP_PORT") or "587")
    user = (os.environ.get("NEWSLETTER_SMTP_USER") or "").strip()
    password = (os.environ.get("NEWSLETTER_SMTP_PASSWORD") or "").strip()
    from_addr, from_name = _from_tuple()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_email
    if text_body:
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
    else:
        msg.set_content(
            "Newsletter în format HTML. Deschide mesajul într-un client de e-mail care suportă HTML.",
            charset="utf-8",
        )
        msg.add_alternative(html_body, subtype="html")

    if unsub_token:
        msg["List-Unsubscribe"] = f"<{build_unsubscribe_url(unsub_token)}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    ctx = _smtp_tls_context()
    with smtplib.SMTP(host, port, timeout=60) as smtp:
        smtp.starttls(context=ctx)
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)
