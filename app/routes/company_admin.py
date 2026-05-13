from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse,RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.models.sqlite_model import fetch_one, fetch_all, execute_query
from app.utils.decorators import company_admin_required 
from fastapi.templating import Jinja2Templates
from app.models.sqlite_company_model import get_db, save_company_settings
import os
import shutil
from pathlib import Path

from app.utils.extractor import extract_text_from_file






from app.utils.db_prompts import (
    list_prompts, 
    insert_prompt, 
    get_prompt_by_id, 
    update_prompt, 
    delete_prompt,
    count_prompts
)

from app.utils.db_rags import (
    list_docs,
    get_document_path,
    chunk_document_text,
    save_uploaded_document,
    delete_company_document,
    revectorize_document,
)

# Activăm protecția direct pe router. Cine nu e Superadmin sau Company Admin cu ID, nici nu intră aici.
router = APIRouter(dependencies=[Depends(company_admin_required)])

templates = Jinja2Templates(directory="app/templates")


# Presupunând că router-ul tău are deja prefix="/company_admin"
@router.get("/dashboard/{tab}")
@router.get("/dashboard")
async def company_dashboard(request: Request, tab: str = None):
    cui = request.session.get('company_cui')
    company_id = request.session.get('company_id')
    

    current_tab = tab if tab else "stats"

    context = {
        "request": request,
        "company_name": request.session.get('company_name'),
        "company_cui": cui,
        "firstname": request.session.get('firstname'),
        "active_tab": current_tab, 
        "title": f"Consolă {current_tab.capitalize()}"
    }

    # 2. LOGICA DE DATA RETRIEVAL (User-like: încarcă doar ce e nevoie)
    if current_tab == "stats":
        context["stats"] = {
            "prompts": await count_prompts(cui),
            "users": 0, 
            "docs": 0   
        }
    elif current_tab == "prompts":
        # Aici injectăm lista pentru tabelul din tabs/prompts.html
        context["prompts"] = await list_prompts(cui)

    elif current_tab == "docs": # Corespunde cu href="/company_admin/dashboard/rags" din nav-ul tău
        # Aici injectăm lista din db_rags.py
        context["documents"] = await list_docs(cui)    
    
    elif current_tab == "users":
        # Membrii companiei curente
        context["company_users"] = await fetch_all(
            """
            SELECT id, firstname, lastname, username, role, is_visible, company_id
            FROM users
            WHERE company_id = ?
            ORDER BY lastname ASC, firstname ASC, id ASC
            """,
            (company_id,),
        )

        # Utilizatori care au ales "vreau să fiu vizibil pentru companii"
        # și nu sunt încă atașați unei companii.
        context["visible_users"] = await fetch_all(
            """
            SELECT id, firstname, lastname, username, role, is_visible, company_id
            FROM users
            WHERE is_visible = 1
              AND company_id IS NULL
              AND (role IS NULL OR role = '' OR role = 'users')
            ORDER BY id DESC
            """
        )
    elif current_tab == "settings":
    # 1. Luăm setările din DB (funcția noastră smart care dă și defaults)
        context["settings"] = await get_company_settings(cui)
    return templates.TemplateResponse(request=request, name="company_admin/dashboard.html", context=context)


@router.get("/users")
async def company_users_alias(request: Request):
    # Link-ul din navbar duce aici; păstrăm dashboard-ul ca sursă unică.
    return RedirectResponse(url="/company_admin/dashboard/users", status_code=303)


@router.post("/users/claim")
async def claim_visible_user(
    request: Request,
    user_id: int = Form(...),
):
    role = request.session.get("role")
    company_id = request.session.get("company_id")

    if role not in ("company_admin", "superadmin") or not company_id:
        raise HTTPException(status_code=403, detail="Acces interzis.")

    target = await fetch_one(
        "SELECT id, company_id, is_visible, role FROM users WHERE id = ?",
        (int(user_id),),
    )
    if not target:
        request.session["flash_messages"] = [
            {"text": "Utilizator inexistent.", "type": "danger"}
        ]
        return RedirectResponse(url="/company_admin/dashboard/users", status_code=303)

    if target["company_id"] is not None:
        request.session["flash_messages"] = [
            {"text": "Utilizatorul este deja înrolat într-o companie.", "type": "warning"}
        ]
        return RedirectResponse(url="/company_admin/dashboard/users", status_code=303)

    if int(target["is_visible"] or 0) != 1:
        request.session["flash_messages"] = [
            {"text": "Utilizatorul nu este disponibil pentru companii.", "type": "warning"}
        ]
        return RedirectResponse(url="/company_admin/dashboard/users", status_code=303)

    target_role = (target["role"] or "").strip()
    # Condiții: user eligibil doar dacă role e NULL/"" sau "users" și e vizibil.
    if target_role not in ("", "users"):
        request.session["flash_messages"] = [
            {"text": "Acest utilizator nu poate fi preluat (rol invalid).", "type": "warning"}
        ]
        return RedirectResponse(url="/company_admin/dashboard/users", status_code=303)

    await execute_query(
        """
        UPDATE users
        SET company_id = ?, is_visible = 0
        WHERE id = ?
          AND company_id IS NULL
          AND is_visible = 1
          AND (role IS NULL OR role = '' OR role = 'users')
        """,
        (int(company_id), int(user_id)),
    )

    request.session["flash_messages"] = [
        {"text": "Utilizator preluat în companie.", "type": "success"}
    ]
    return RedirectResponse(url="/company_admin/dashboard/users", status_code=303)


##########################################################################
##########################################################################
##########################################################################
### Rute pentru managementul prompts (CRUD)###############################

@router.post("/dashboard/prompts/add")
async def add_prompt_action(
    request: Request,
    name: str = Form(...),
    content: str = Form(...),
    p_type: str = Form("General")
):
    cui = request.session.get('company_cui')
    
    # Acum succesul va fi un dicționar, deci verificăm cheia 'status'
    result = await insert_prompt(cui, name, content, p_type, "active")
    
    # Redirect înapoi la tab-ul de prompts
    return RedirectResponse(url="/company_admin/dashboard/prompts", status_code=303)

@router.get("/dashboard/prompts/delete/{prompt_id}")
async def remove_prompt(request: Request, prompt_id: int):
    cui = request.session.get('company_cui')
    if not cui: return RedirectResponse(url="/auth/login", status_code=303)
    
    await delete_prompt(cui, prompt_id)
    return RedirectResponse(url="/company_admin/dashboard/prompts", status_code=303)  

@router.post("/dashboard/prompts/edit")
async def edit_prompt_action(
    request: Request,
    prompt_id: int = Form(...),
    name: str = Form(...),
    content: str = Form(...),
    p_type: str = Form(...)
):
    cui = request.session.get('company_cui')
    if not cui: return RedirectResponse(url="/auth/login", status_code=303)

    # Update pe NVMe
    await update_prompt(cui, prompt_id, name, content, p_type, "active")
    
    return RedirectResponse(url="/company_admin/dashboard/prompts", status_code=303)

##########################################################################
##########################################################################
##########################################################################
### Rute pentru managementul RAGs (Upload & Chunking)####################



@router.post("/dashboard/rag/upload")
async def upload_document_action(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    cui = request.session.get('company_cui')
    if not cui:
        return RedirectResponse(url="/auth/login", status_code=303)

    # 1. Calea pe NVMe
    file_path = get_document_path(cui, file.filename)

    # 2. Salvare fizică
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        print(f"❌ [NVMe] Eroare: {e}")
        return RedirectResponse(url="/company_admin/dashboard/docs", status_code=303)

    # 3. Salvare în DB (cu al treilea argument data_path ca să nu crape)
    doc_id = await save_uploaded_document(cui, file.filename, str(file_path))

    # 4. Background Task local
    def process_document():
        content = extract_text_from_file(str(file_path))
        if content:
            import asyncio
            asyncio.run(chunk_document_text(cui, doc_id, content))
            print(f"✅ [RAG] Gata: {file.filename}")

    if doc_id:
        background_tasks.add_task(process_document)

    # Simplu, fără parametri care să te pună pe drumuri
    return RedirectResponse(url="/company_admin/dashboard/docs", status_code=303)



@router.post("/dashboard/rag/delete/{doc_id}")
async def delete_document_action(doc_id: int, request: Request):
    cui = request.session.get('company_cui')
    if not cui:
        return RedirectResponse(url="/auth/login", status_code=303)

    # Executăm ștergerea (Așteptăm cuminți să termine, ca în Flask)
    success, message = await delete_company_document(cui, doc_id)

    # Ne întoarcem la bază, simplu, fără 'active_tabs' sau alte balasturi
    return RedirectResponse(url="/company_admin/dashboard/docs", status_code=303)


@router.post("/dashboard/rag/revectorize/{doc_id}")
async def revectorize_document_action(
    doc_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
):
    cui = request.session.get('company_cui')
    if not cui:
        return RedirectResponse(url="/auth/login", status_code=303)

    def run_revectorize():
        import asyncio

        ok, msg = asyncio.run(revectorize_document(cui, doc_id))
        print(f"{'✅' if ok else '❌'} [RAG] Re-vectorizare doc {doc_id}: {msg}")

    background_tasks.add_task(run_revectorize)
    return RedirectResponse(url="/company_admin/dashboard/docs", status_code=303)


async def get_company_settings(cui):
    conn = await get_db(cui)
    # Default-uri noi pentru Scraping
    settings = {
        'rag_temperature': 0.1,
        'rag_top_k': 5,
        'rag_threshold': 0.45,
        'wp_scrape_url': '',
        'wp_scrape_enabled': 'off', # Folosim 'on'/'off' pentru checkbox-urile HTML
        'wp_scrape_hours': '08:00, 18:00' # Default: de două ori pe zi
    }
    
    if not conn: 
        return settings
    
    try:
        async with conn.execute("SELECT key, value FROM company_settings") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                key = row['key']
                val = row['value']
                # Parsăm în funcție de tip
                if key in ['rag_temperature', 'rag_threshold']:
                    settings[key] = float(val)
                elif key in ['rag_top_k']:
                    settings[key] = int(val)
                else:
                    settings[key] = val
        return settings
    finally:
        await conn.close()



@router.post("/dashboard/settings/save")
async def save_settings(request: Request):
    cui = request.session.get('company_cui')
    if not cui:
        return RedirectResponse(url="/auth/login", status_code=303)
    
    form_data = await request.form()
    
    # Colectăm tot, inclusiv noile setări de scrap
    settings_to_save = {
        "rag_temperature": form_data.get("rag_temperature"),
        "rag_top_k": form_data.get("rag_top_k"),
        "rag_threshold": form_data.get("rag_threshold"),
        "wp_scrape_url": form_data.get("wp_scrape_url", "").strip(),
        "wp_scrape_enabled": form_data.get("wp_scrape_enabled", "off"),
        "wp_scrape_hours": form_data.get("wp_scrape_hours", "08:00, 18:00")
    }
    
    # 1. Salvăm în DB
    await save_company_settings(cui, settings_to_save)
    
    # 2. TODO: Aici vom chema scheduler.update_job(cui, settings_to_save)
    # ca să actualizăm orele de rulare fără restart la server.
    
    return RedirectResponse(url="/company_admin/dashboard/settings", status_code=303)  



from app.utils.scraping.scraping_all import start_the_beast, active_syncs


@router.post("/sync-data-source")
async def sync_data_source_endpoint(request: Request, background_tasks: BackgroundTasks):
    cui = request.session.get('company_cui')
    if not cui:
        return JSONResponse({"status": "error", "message": "Sesiune invalidă!"}, status_code=401)

    # 1. Luăm TOATE setările dintr-o singură lovitură (funcția ta se ocupă de DB)
    settings = await get_company_settings(cui)
    
    # 2. Extragem URL-ul (dacă nu există în DB, funcția ta returnează string gol '')
    target_url = settings.get('wp_scrape_url', '').strip()

    # 3. Validăm URL-ul și îi punem protocolul dacă lipsește (că am văzut ce pățim)
    if not target_url:
        return JSONResponse({"status": "error", "message": "⚠️ Sursă de date (URL) lipsă în setări!"})
    
    if not target_url.startswith(('http://', 'https://')):
        target_url = f"https://{target_url}"


    if active_syncs.get(str(cui)):
        return JSONResponse({"status": "error", "message": "O sincronizare este deja în curs!"})

    # 5. PORNEȘTE BESTIA (Atenție la ordine: cui, apoi url)
    background_tasks.add_task(start_the_beast, str(cui), target_url)

    return {
        "status": "success", 
        "message": "Sincronizarea a pornit. Verifică terminalul pentru progres."
    }



@router.get("/sync-status")
async def get_sync_status(request: Request):
    cui = request.session.get('company_cui')
    is_running = active_syncs.get(str(cui), False)
    return {"is_running": is_running}