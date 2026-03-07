from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import os
import uuid
from fastapi import Request
from fastapi.responses import RedirectResponse
from passlib.context import CryptContext
import sqlite3

import json
import logging
import hashlib
import hmac
import aiosqlite

from app.models.sqlite_model import fetch_one, execute_query, fetch_all
from app.utils.notifier import send_telegram_admin_alert, send_telegram_company_approval
from app.utils.session import sync_user_session



router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
async def auth_page(request: Request):
    
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request}
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request}
    )

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
@router.post("/login", name="login")
async def login(request: Request):
    form_data = await request.form()
    email = form_data.get('email')
    password = form_data.get('password')
    
    # Verificăm credențialele în baza de date
    conn = sqlite3.connect('app/database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, password_hash FROM users WHERE email = ?', (email,))
    user = cursor.fetchone()
    conn.close()
    
    if user and hash_password(user[1], password):
        # Autentificare reușită
        request.session['user_id'] = user[0]
        return templates.TemplateResponse("main/home.html", {"request": request})
    
    # Autentificare eșuată
    return templates.TemplateResponse("auth/login.html", {"request": request, "error": "Email sau parolă incorectă!"})


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
        # User Nou -> Îl băgăm în DB
        # Notă: Am pus provider 'telegram' ca să știm de unde a venit
        await execute_query('''
            INSERT INTO users (oauth_id, firstname, lastname, username, photo_url, role) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (oauth_id, firstname, lastname, username, photo_url, 'none'))
        
        # Luăm userul proaspăt creat pentru a-i obține ID-ul intern
        user = await fetch_one('SELECT * FROM users WHERE oauth_id = ?', (oauth_id,))
        current_role = 'none'
        target_path = '/auth/profile'
    else:
      
        user_id = user['id']

    # Marea Sincronizare
    await sync_user_session(request, user_id)

    return RedirectResponse(url="/auth/profile")

@router.get("/profile", name="profile")
async def profile(request: Request):
    user_id = request.session.get('user_id')
    if not user_id:
        return RedirectResponse(url="/auth/login")

    # Luăm datele userului din database.db
    user = await fetch_one('SELECT * FROM users WHERE id = ?', (user_id,))
    
    # Luăm și lista de companii ca să aibă ce alege în dropdown
    companies = await fetch_all('SELECT company_id, name FROM companies')

    return templates.TemplateResponse("auth/profile.html", {
        "request": request,
        "user": user,
        "companies": companies
    })


###############################################
###############################################
###############################################
@router.post("/profile/update")
async def update_profile(request: Request):
    user_id = request.session.get('user_id')
    username = request.session.get('username')
    form_data = await request.form()
    
    intent = form_data.get("user_intent") # 'be_visible' sau 'be_admin'
    firstname = form_data.get("firstname")
    lastname = form_data.get("lastname")

    # Stabilim rolul și vizibilitatea
    if intent == "be_admin":
        new_role = "pending_admin"
        is_visible = 0
    else:
        new_role = "users"  # Rolul normal pentru vizibilitate
        is_visible = 1 if intent == "be_visible" else 0

    # UPDATE în SQLite
    await execute_query('''
        UPDATE users 
        SET firstname=?, lastname=?, role=?, is_visible=? 
        WHERE id=?
    ''', (firstname, lastname, new_role, is_visible, user_id))

    # REFRESH SESIUNE - să știe app-ul instant cine e el acum
    await sync_user_session(request, user_id)

    

    # 🚨 MOMENTUL TURBO: Alertă Telegram
  
    if intent == "be_admin":
        msg = f"🔔 *Cerere Admin*: {firstname} {lastname}"
        send_telegram_admin_alert(msg, user_id)
        # Redirecționăm către formularul de completare date firmă (GET)
        return RedirectResponse(url="/auth/create_company", status_code=303)
    if intent == "be_visible":
        return RedirectResponse(url="/auth/profile?success=1", status_code=303)


# Adaugă această rută GET pentru a afișa formularul
@router.get("/create_company")
async def show_create_company_form(request: Request):
    return templates.TemplateResponse("auth/create_company.html", {"request": request})





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
    
    # 🚨 7. MOMENTUL TURBO: Generare Token și Alertă Telegram
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