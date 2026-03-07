from fastapi import APIRouter, Request, Depends,Form, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse,RedirectResponse
from fastapi.templating import Jinja2Templates
from app.models.sqlite_model import fetch_one, fetch_all
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
    delete_company_document
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
        # Exemplu pentru viitor: context["users"] = await list_users(company_id)
        pass
    elif current_tab == "settings":
    # 1. Luăm setările din DB (funcția noastră smart care dă și defaults)
        context["settings"] = await get_company_settings(cui)
    return templates.TemplateResponse("company_admin/dashboard.html", context)


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


async def get_company_settings(cui):
    conn = await get_db(cui)
    # Punem default-urile aici direct, ca fallback solid
    settings = {
        'rag_temperature': 0.1,
        'rag_top_k': 5,
        'rag_threshold': 0.45,
        'system_prompt': 'Ești un asistent tehnic util.'
    }
    
    if not conn: 
        print(f"⚠️ [RAG] Nu s-a putut deschide DB pentru CUI {cui}")
        return settings # Returnăm măcar default-urile
    
    try:
        async with conn.execute("SELECT key, value FROM company_settings") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                key = row['key']
                val = row['value']
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
    
    # Extragem datele din formular
    form_data = await request.form()
    
    # Filtrăm doar cheile care ne interesează pentru RAG
    settings_to_save = {
        "rag_temperature": form_data.get("rag_temperature"),
        "rag_top_k": form_data.get("rag_top_k"),
        "rag_threshold": form_data.get("rag_threshold"),
        "system_prompt": form_data.get("system_prompt")
    }
    
    # Salvăm în DB
    success = await save_company_settings(cui, settings_to_save)
    
    # Redirecționăm înapoi la tab-ul de settings cu un mesaj (opțional)
    return RedirectResponse(
        url="/company_admin/dashboard/settings", 
        status_code=303
    )    