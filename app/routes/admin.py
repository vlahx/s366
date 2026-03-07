import hashlib
import os
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.utils.decorators import superadmin_required
from app.models.sqlite_model import fetch_all, execute_query, fetch_one
from app.models.sqlite_company_model import init_company_db, COMPANIES_ROOT
from app.utils.system import get_system_stats # Importăm mecanica
from app.utils.session import sync_user_session


router = APIRouter(
    dependencies=[Depends(superadmin_required)]
)

templates = Jinja2Templates(directory="app/templates")

@router.get("/dashboard")
async def admin_dashboard(request: Request):
    # 1. Hardware Stats (din utils/system.py)
    stats = get_system_stats()

    # 2. Utilizatori (cu JOIN pentru numele companiei)
    users = await fetch_all("""
        SELECT u.id, u.firstname, u.lastname, u.username, u.role, u.company_id, c.name as company_name 
        FROM users u
        LEFT JOIN companies c ON u.company_id = c.company_id
    """)

    # 3. Companii (Toate, dar le sortăm în template sau aici)
    # Punem status='pending' primele
    companies = await fetch_all("SELECT * FROM companies ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, name ASC")

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "stats": stats,
        "users": users,
        "companies": companies,
        "title": "Admin Panel | s366_turbo"
    })

@router.get("/api/stats")
async def api_stats(request: Request):
    if request.session.get("role") != "superadmin":
        return JSONResponse(content={"error": "Acces interzis!"}, status_code=403)

    stats = get_system_stats()
    return JSONResponse(content=stats)

@router.get("/pending-companies")
async def list_pending_companies(request: Request):
    # Folosim fetch_all din modelul tău
    companies = await fetch_all("SELECT * FROM companies WHERE status = 'pending'")
    return templates.TemplateResponse("admin/pending.html", {
        "request": request, 
        "companies": companies
    })

@router.get("/approve/{u_id}/{token}")
async def approve_admin_via_telegram(request: Request, u_id: int, token: str):
    secret = os.getenv("APP_SECRET_KEY", "schimba-ma-frate")
    expected_token = hashlib.sha256(f"{u_id}{secret}".encode()).hexdigest()[:16]
    
    if token != expected_token:
        return HTMLResponse(content="❌ Token Invalid!", status_code=403)

    # Promovăm userul la rolul de company_admin
    await execute_query("UPDATE users SET role = 'company_admin' WHERE id = ?", (u_id,))
    
    # Arătăm o pagină de succes care respectă tema dark mode prin inline style simplu
    return HTMLResponse(content=f"""
        <body style="background: #121212; color: #00ff00; text-align: center; font-family: sans-serif; padding: 50px;">
            <h1>🚀 User {u_id} Aprobat!</h1>
            <p style="color: #ccc;">Acum este Company Admin.</p>
        </body>
    """)

@router.get("/approve_company/{c_id}/{token}")
async def approve_company_via_telegram(request: Request, c_id: int, token: str):
    secret = os.getenv("APP_SECRET_KEY", "schimba-ma-frate")
    # Generăm token-ul de verificare pentru ID-ul companiei
    expected_token = hashlib.sha256(f"comp_{c_id}{secret}".encode()).hexdigest()[:16]
    
    if token != expected_token:
        return HTMLResponse(content="❌ Token Companie Invalid!", status_code=403)

    # 1. Luăm datele firmei (avem nevoie de CUI pentru init_db)
    company = await fetch_one("SELECT name, cui FROM companies WHERE company_id = ?", (c_id,))
    if not company:
        return HTMLResponse(content="❌ Compania nu există!", status_code=404)
    
    cui = company['cui']
    name = company['name']

    try:
        # 2. Activăm compania în baza centrală
        await execute_query("UPDATE companies SET status = 'active' WHERE company_id = ?", (c_id,))
        
        # 3. Inițializăm infrastructura pe NVMe (Baza Metadata + Foldere)
        # Aici apelăm funcția ta din sqlite_model
        from app.models.sqlite_company_model import init_company_db
        success = await init_company_db(cui)
        
        if not success:
            raise Exception("Eroare la crearea metadata.db pe NVMe")

        # 4. Creăm folderul de documente RAG (docs)
        company_docs_path = COMPANIES_ROOT / str(cui) / "docs"
    
        # os.makedirs sau Path.mkdir - ambele funcționează
        os.makedirs(str(company_docs_path), exist_ok=True)

        return HTMLResponse(content=f"""
            <body style="background: #0d1117; color: #58a6ff; text-align: center; font-family: sans-serif; padding: 50px;">
                <div style="border: 1px solid #30363d; padding: 20px; border-radius: 10px; display: inline-block;">
                    <h1 style="color: #238636;">✅ {name} Activată!</h1>
                    <p style="color: #8b949e;">CUI: {cui} | Infrastructură NVMe pregătită.</p>
                    <p style="font-size: 0.8rem; color: #484f58;">Status: metadata.db creat | /docs creat</p>
                </div>
            </body>
        """)

    except Exception as e:
        print(f"❌ Eroare activare firmă: {e}")
        return HTMLResponse(content=f"❌ Eroare tehnică la activare: {str(e)}", status_code=500)    

@router.get("/impersonate/{user_id}")
async def impersonate_user(request: Request, user_id: int):
    # 1. Siguranță maximă: Verificăm dacă cel care cere e Superadmin
    if request.session.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Acces interzis!")

    # 2. Tragem datele userului țintă din DB
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există")

    # 3. Facem swap la sesiune
    # Salvăm ID-ul de superadmin original într-o cheie separată (ca să putem reveni)
    if not request.session.get("original_admin_id"):
        request.session["original_admin_id"] = request.session.get("user_id")

    await sync_user_session(request, user_id)

    # 4. Redirecționăm către dashboard-ul specific rolului noului user
    if user["role"] == "company_admin":
        return RedirectResponse(url="/company_admin/dashboard")
    return RedirectResponse(url="/")

@router.get("/stop-impersonation")
async def stop_impersonation(request: Request):
    # Revenim la contul de Superadmin
    orig_id = request.session.get("original_admin_id")
    if not orig_id:
        return RedirectResponse(url="/")
    
    # Reîncărcăm datele de Superadmin (sau facem un simplu query)
    # Aici presupunem că rolul e superadmin fix
    request.session["user_id"] = orig_id
    request.session["role"] = "superadmin"
    del request.session["original_admin_id"]
    
    return RedirectResponse(url="/admin/dashboard")