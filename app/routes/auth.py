from typing import Optional
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.responses import RedirectResponse

import os
import uuid
from fastapi import Request
from fastapi.responses import RedirectResponse
from passlib.context import CryptContext
import sqlite3
import httpx
import json
import logging
import hashlib
import hmac
import aiosqlite

from app.models.sqlite_model import fetch_one, execute_query, fetch_all
from app.utils.notifier import send_telegram_admin_alert, send_telegram_company_approval
from app.utils.hosting_checkout import public_base_url
from app.utils.session import sync_user_session
from app.utils.billing_profile import billing_readiness, clean_row_for_forms, safe_internal_path



router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _login_template_context(request: Request) -> dict:
    o = public_base_url(str(request.base_url).rstrip("/"))
    return {
        "request": request,
        "seo_og_image_abs": f"{o}/static/images/og/lo-shack.png",
        "seo_tw_image_abs": f"{o}/static/images/robo/lo-shack.png",
    }


@router.get("/", response_class=HTMLResponse)
async def auth_page(request: Request, next: Optional[str] = None):
    sn = safe_internal_path(next)
    if sn:
        request.session["oauth_next"] = sn
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context=_login_template_context(request),
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: Optional[str] = None):
    sn = safe_internal_path(next)
    if sn:
        request.session["oauth_next"] = sn
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context=_login_template_context(request),
    )

GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
GOOGLE_CLIENT_SECRET = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
GOOGLE_REDIRECT_URI = (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()


@router.get("/google")
async def login_google():
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        logging.error("Google OAuth: lipsesc GOOGLE_CLIENT_ID sau GOOGLE_REDIRECT_URI în mediu (.env).")
        return RedirectResponse(url="/auth/login?error=google_config")
    params = {
        "response_type": "code",
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "scope": "openid profile email",
    }
    google_auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url=google_auth_url)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
):
    if error:
        logging.warning("Google OAuth denied/error param: %s", error)
        return RedirectResponse(url="/auth/login?error=google_denied")
    if not code:
        return RedirectResponse(url="/auth/login?error=google_no_code")
    if not GOOGLE_CLIENT_SECRET:
        logging.error("Google OAuth: lipsește GOOGLE_CLIENT_SECRET în mediu (.env).")
        return RedirectResponse(url="/auth/login?error=google_config")

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI,
            },
        )
        try:
            token_data = token_response.json()
        except json.JSONDecodeError:
            raw = (token_response.text or "")[:800]
            logging.warning(
                "Google token răspuns non-JSON: status=%s raw=%r",
                token_response.status_code,
                raw,
            )
            return RedirectResponse(url="/auth/login?error=google_token")

        if not isinstance(token_data, dict):
            logging.warning(
                "Google token body neașteptat (nu e obiect JSON): status=%s type=%s",
                token_response.status_code,
                type(token_data).__name__,
            )
            return RedirectResponse(url="/auth/login?error=google_token")

        access_token = token_data.get("access_token")
        if token_response.status_code != 200 or not access_token:
            logging.warning(
                "Google token exchange failed: status=%s error=%s body_keys=%s",
                token_response.status_code,
                token_data.get("error"),
                list(token_data.keys()) if isinstance(token_data, dict) else None,
            )
            return RedirectResponse(url="/auth/login?error=google_token")

        user_info = await client.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_data = user_info.json()

    # 3. Logica de bază de date (identică cu Telegram)
    oauth_id = user_data.get('id')
    firstname = user_data.get('given_name', '')
    lastname = user_data.get('family_name', '')
    username = user_data.get('email', '') 
    photo_url = user_data.get('picture', '')

    user = await fetch_one('SELECT * FROM users WHERE oauth_id = ?', (oauth_id,))
    
    if not user:
        await execute_query('''
            INSERT INTO users (oauth_id, firstname, lastname, username, photo_url, role) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (oauth_id, firstname, lastname, username, photo_url, 'none'))
        user = await fetch_one('SELECT * FROM users WHERE oauth_id = ?', (oauth_id,))
    
    user_id = user['id']

    # 4. Sincronizare sesiune (Marea Sincronizare)
    await sync_user_session(request, user_id)

    next_raw = request.session.pop("oauth_next", None)
    target = safe_internal_path(next_raw) or "/auth/profile"
    return RedirectResponse(url=target)


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
@router.get("/telegram", name="telegram_auth")
async def telegram_auth(request: Request):
    # 1. Extragem parametrii din query string
    auth_data = dict(request.query_params)
    received_hash = auth_data.pop('hash', None)
    
    if not received_hash:
        return RedirectResponse(url="/auth/login?error=missing_hash")

    # 2. Validarea Hash-ului Telegram
    data_check_list = [f"{k}={v}" for k, v in sorted(auth_data.items())]
    data_check_string = "\n".join(data_check_list)
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if received_hash != expected_hash:
        return RedirectResponse(url="/auth/login?error=security")

    # 3. Extragem datele utilizatorului
    oauth_id = auth_data.get('id')
    firstname = auth_data.get('first_name', '')
    lastname = auth_data.get('last_name', '')
    username = auth_data.get('username', '')
    photo_url = auth_data.get('photo_url', '')

    # 4. Operațiuni pe SQLite (Folosind handler-ul tău asincron)
    # Căutăm userul după oauth_id (care e tg_id-ul)
    user = await fetch_one('SELECT * FROM users WHERE oauth_id = ?', (oauth_id,))
    
    if not user:
        await execute_query(
            """
            INSERT INTO users (oauth_id, firstname, lastname, username, photo_url, role) 
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (oauth_id, firstname, lastname, username, photo_url, "none"),
        )
        user = await fetch_one("SELECT * FROM users WHERE oauth_id = ?", (oauth_id,))

    user_id = user["id"]

    await sync_user_session(request, user_id)
    request.session["flash_messages"] = [{"text": "Te-ai logat cu succes!", "type": "success"}]
    next_raw = request.session.pop("oauth_next", None)
    target = safe_internal_path(next_raw) or "/auth/profile"
    return RedirectResponse(url=target)

@router.get("/profile", name="profile")
async def profile(
    request: Request,
    billing_required: int = 0,
    next: Optional[str] = None,
):
    user_id = request.session.get("user_id")
    if not user_id:
        dest = quote(str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""))
        return RedirectResponse(url=f"/auth/login?next={dest}")

    if billing_required:
        bn = safe_internal_path(next)
        dest = "/auth/billing" + (f"?next={quote(bn)}" if bn else "")
        return RedirectResponse(url=dest, status_code=303)

    user = await fetch_one(
        """
        SELECT u.*, c.name AS company_name_join
        FROM users u
        LEFT JOIN companies c ON u.company_id = c.company_id
        WHERE u.id = ?
        """,
        (user_id,),
    )
    user_d = clean_row_for_forms(dict(user))
    if user_d.get("company_name_join") and not user_d.get("company_name"):
        user_d["company_name"] = user_d["company_name_join"]

    company = None
    if user_d.get("company_id"):
        company = await fetch_one(
            "SELECT * FROM companies WHERE company_id = ?",
            (user_d["company_id"],),
        )

    company_d = clean_row_for_forms(dict(company)) if company else None
    br = billing_readiness(user_d, company_d)

    return templates.TemplateResponse(
        request=request,
        name="auth/profile.html",
        context={
            "request": request,
            "user": user_d,
            "company": company_d,
            "billing": br,
        },
    )


async def _apply_billing_from_form(user_id: int, form_data) -> str:
    inv_type = (form_data.get("invoice_customer_type") or "").strip().upper()
    if inv_type in ("PF", "PJ"):
        ic = _form_strip(form_data, "invoice_country") or "RO"
        await execute_query(
            """
            UPDATE users SET
                invoice_customer_type=?,
                invoice_full_name=?,
                invoice_street=?,
                invoice_city=?,
                invoice_county=?,
                invoice_postal_code=?,
                invoice_country=?,
                invoice_phone=?
            WHERE id=?
            """,
            (
                inv_type,
                _form_strip(form_data, "invoice_full_name"),
                _form_strip(form_data, "invoice_street"),
                _form_strip(form_data, "invoice_city"),
                _form_strip(form_data, "invoice_county"),
                _form_strip(form_data, "invoice_postal_code"),
                ic,
                _form_strip(form_data, "invoice_phone"),
                user_id,
            ),
        )
    if inv_type == "PJ":
        urow = await fetch_one("SELECT company_id FROM users WHERE id=?", (user_id,))
        cid = urow["company_id"] if urow else None
        if cid:
            vat_raw = form_data.get("company_is_vat_payer")
            is_vat = 1 if vat_raw in ("on", "1", "true", "yes") else 0
            coc = _form_strip(form_data, "company_invoice_country") or "RO"
            await execute_query(
                """
                UPDATE companies SET
                    reg_com=?,
                    invoice_legal_name=?,
                    invoice_street=?,
                    invoice_city=?,
                    invoice_county=?,
                    invoice_postal_code=?,
                    invoice_country=?,
                    is_vat_payer=?
                WHERE company_id=?
                """,
                (
                    _form_strip(form_data, "company_reg_com"),
                    _form_strip(form_data, "company_invoice_legal_name"),
                    _form_strip(form_data, "company_invoice_street"),
                    _form_strip(form_data, "company_invoice_city"),
                    _form_strip(form_data, "company_invoice_county"),
                    _form_strip(form_data, "company_invoice_postal_code"),
                    coc,
                    is_vat,
                    cid,
                ),
            )
    return inv_type


@router.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request, next: Optional[str] = None):
    user_id = request.session.get("user_id")
    if not user_id:
        dest = quote("/auth/billing" + (f"?next={next}" if next else ""))
        return RedirectResponse(url=f"/auth/login?next={dest}")

    user = await fetch_one(
        """
        SELECT u.*, c.name AS company_name_join
        FROM users u
        LEFT JOIN companies c ON u.company_id = c.company_id
        WHERE u.id = ?
        """,
        (user_id,),
    )
    user_d = clean_row_for_forms(dict(user))
    if user_d.get("company_name_join") and not user_d.get("company_name"):
        user_d["company_name"] = user_d["company_name_join"]

    company = None
    if user_d.get("company_id"):
        company = await fetch_one(
            "SELECT * FROM companies WHERE company_id = ?",
            (user_d["company_id"],),
        )
    company_d = clean_row_for_forms(dict(company)) if company else None
    br = billing_readiness(user_d, company_d)
    billing_next = safe_internal_path(next)

    return templates.TemplateResponse(
        request=request,
        name="auth/billing.html",
        context={
            "request": request,
            "user": user_d,
            "company": company_d,
            "billing": br,
            "billing_next": billing_next,
        },
    )


@router.post("/billing/save")
async def billing_save(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/auth/login", status_code=303)

    form_data = await request.form()
    await _apply_billing_from_form(int(user_id), form_data)
    await sync_user_session(request, int(user_id))

    u = await fetch_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not u:
        return RedirectResponse(url="/auth/login", status_code=303)
    ud = dict(u)
    co = None
    cid = ud.get("company_id")
    if cid:
        co = await fetch_one(
            "SELECT * FROM companies WHERE company_id=?",
            (cid,),
        )
    u_d = clean_row_for_forms(ud)
    co_d = clean_row_for_forms(dict(co)) if co else None

    next_url = safe_internal_path(form_data.get("billing_next"))
    if next_url and billing_readiness(u_d, co_d)["ok"]:
        request.session["flash_messages"] = [
            {"text": "Date facturare salvate. Continuă comanda.", "type": "success"}
        ]
        return RedirectResponse(url=next_url, status_code=303)

    request.session["flash_messages"] = [
        {"text": "Date salvate. Verifică câmpurile marcate ca obligatorii.", "type": "warning"}
    ]
    redir = "/auth/billing"
    if next_url:
        redir = f"/auth/billing?next={quote(next_url)}"
    return RedirectResponse(url=redir, status_code=303)


def _form_strip(form_data, key: str):
    v = form_data.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


###############################################
@router.post("/profile/update")
async def update_profile(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/auth/login", status_code=303)

    form_data = await request.form()

    intent = form_data.get("user_intent") # 'be_visible' sau 'be_admin'
    firstname = form_data.get("firstname")
    lastname = form_data.get("lastname")

    # Stabilim rolul și vizibilitatea
    if intent == "be_admin":
        new_role = "pending_admin"
        is_visible = 0
    elif intent == "be_visible":
        new_role = "users" # Sau ce rol standard ai
        is_visible = 1
    else:
        # Cazul în care se schimbă doar numele, păstrăm rolul curent
        new_role = request.session.get('role')
        is_visible = request.session.get('is_visible', 0)

    # UPDATE în SQLite
    await execute_query('''
        UPDATE users 
        SET firstname=?, lastname=?, role=?, is_visible=? 
        WHERE id=?
    ''', (firstname, lastname, new_role, is_visible, user_id))

    # REFRESH SESIUNE - să știe app-ul instant cine e el acum
    await sync_user_session(request, user_id)

    
    

    # 🚨 Alertă Telegram (înregistrare admin)
  
    if intent == "be_admin":
        msg = f"🔔 *Cerere Admin*: {firstname} {lastname}"
        send_telegram_admin_alert(msg, user_id)
        # Redirecționăm către formularul de completare date firmă (GET)
        request.session["flash_messages"] = [{"text": "Cererea afost trimisa, in cel mai scurt timp posibil va apare aprobarea!", "type": "success"}]
        return RedirectResponse(url="/auth/create_company", status_code=303)
    
    if intent == "be_visible":
        request.session["flash_messages"] = [{"text": "Situatia ta s-a schimbat, de acum poti fi vazut de catre administratorii companiilor!", "type": "success"}]
        return RedirectResponse(url="/auth/profile?success=1", status_code=303)

    request.session["flash_messages"] = [{"text": "Profil actualizat!", "type": "success"}]
    return RedirectResponse(url="/auth/profile?success=1", status_code=303)




# Adaugă această rută GET pentru a afișa formularul
@router.get("/create_company")
async def show_create_company_form(request: Request):
    return templates.TemplateResponse(request=request, name="auth/create_company.html", context={"request": request})





@router.post("/create_company")
async def create_company(request: Request):
    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url="/auth/login", status_code=303)

    form_data = await request.form()
    name = form_data.get("name", "")
    cui = form_data.get("cui", "")

    if not name or not cui:
        return RedirectResponse(url="/auth/profile?error=missing_fields", status_code=303)

    # 1. Verificăm dacă firma există deja
    existing = await fetch_one("SELECT company_id FROM companies WHERE cui = ?", (cui,))
    if existing:
        return RedirectResponse(url="/auth/profile?error=exists", status_code=303)

    # 2. Date unice
    slug = name.lower().replace(" ", "-").replace(".", "")
    api_key = str(uuid.uuid4())

    # 3. Inserăm compania
    await execute_query('''
        INSERT INTO companies (name, cui, slug, api_key, status)
        VALUES (?, ?, ?, ?, "pending")
    ''', (name, cui, slug, api_key))

    # 4. Luăm noul company_id
    new_comp = await fetch_one("SELECT company_id FROM companies WHERE cui = ?", (cui,))
    c_id = new_comp['company_id']

    # 5. Legăm userul de firmă
    await execute_query('''
        UPDATE users 
        SET company_id = ?, role = 'company_admin' 
        WHERE id = ?
    ''', (c_id, user_id))

    # 6. Sync Sesiune
    await sync_user_session(request, user_id)
    
    # 🚨 7. Generare token și alertă Telegram (firmă nouă)
    secret = os.getenv("APP_SECRET_KEY", "schimba-ma-frate")
    # Generăm același tip de token pe care îl așteaptă ruta de aprobare
    token = hashlib.sha256(f"comp_{c_id}{secret}".encode()).hexdigest()[:16]
    

    # Trimitem mesajul cu buton către Telegram
    msg = (
        f"🚀 *Cerere Firmă Nouă*\n\n"
        f"🏢 *Nume:* {name}\n"
        f"🆔 *CUI:* `{cui}`\n"
        f"👤 *Admin:* {request.session.get('firstname')} {request.session.get('lastname')}\n"
        f"🔗 *Slug:* {slug}"
    )
    
    send_telegram_company_approval(msg,c_id)

    # 8. Redirect conform strategiei tale
    return RedirectResponse(url="/company_admin/dashboard", status_code=303)

@router.get("/logout", name="logout")
async def logout(request: Request):
    # 1. Ștergem tot ce e în sesiune
    request.session.clear()
    
    # 2. Îl trimitem la login cu un mesaj (opțional)
    # Putem adăuga un parametru în URL ca să-i afișăm o notificare "Te-ai delogat cu succes"
    return RedirectResponse(url="/auth/login?msg=logged_out")