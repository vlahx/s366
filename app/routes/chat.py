# routes/chat.py - Rutele pentru chat și gestionarea conversațiilor
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import uuid
import aiosqlite

from app.utils.payload_builder import build_llm_payload
from app.utils.db_helpers import get_db_path
from app.utils.sqlite_handler import SQLiteHandler

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse("chat/chat.html", {"request": request})

@router.post("/send")
async def handle_chat(request: Request):
    # Luăm serviciul din app.state (inițializat o singură dată în main.py)
    llm_service = request.app.state.llm_service
    
    data = await request.json()
    user_message = data.get("message")
    audio_b64 = data.get("audio_b64")
    conv_uuid = data.get("conversation_uuid") or str(uuid.uuid4())
    
    user_id = request.session.get('user_id')
    user_firstname = request.session.get('firstname', 'Vizitator')
    user_lastname = request.session.get('lastname', '')
    company_id = request.session.get('company_id') #or '1'.strip()  # Fallback la '1' dacă nu există în sesiune
    company_cui = request.session.get('company_cui') #or '39838810'.strip()  # Fallback la '39838810' dacă nu există în sesiune
    user_role = request.session.get('role', 'user')  # Fallback la 'user' dacă nu există în sesiune

    payload = await build_llm_payload(
        user_message=user_message if not audio_b64 else "",
        user_id=user_id,
        user_role=user_role,
        user_firstname=user_firstname,
        user_lastname=user_lastname,
        company_id=company_id,
        company_cui=company_cui,
        conversation_uuid=conv_uuid
    )

    if audio_b64:
        import base64
        audio_bytes = base64.b64decode(audio_b64)
        gen = llm_service.get_voice_response(audio_bytes, payload)
    else:
        gen = llm_service.get_internal_response(payload)

    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"X-Conversation-UUID": conv_uuid}
    )

@router.get("/api/sessions")
async def get_sessions(request: Request):
    try:
        user_id = request.session.get('user_id')
        company_id = request.session.get('company_id')
        db_path = get_db_path(user_id, company_id)
        
        if not db_path:
            return []

        handler = SQLiteHandler(db_path)
        # Acum returnează datele din chat_sessions, ceea ce este mult mai rapid
        sessions = await handler.get_all_discussions_summary()
        return sessions
    except Exception as e:
        print(f"[CRITICAL] Eroare API Sessions: {str(e)}")
        return []

@router.get("/api/messages/{uuid}")
async def get_messages(uuid: str, request: Request):
    try:
        user_id = request.session.get('user_id')
        company_id = request.session.get('company_id')
        db_path = get_db_path(user_id, company_id)
        
        if not db_path:
            return []
            
        handler = SQLiteHandler(db_path)
        # Acum returnează și titlul/pinned din chat_sessions via JOIN
        messages = await handler.get_conversation(uuid)
        return messages
    except Exception as e:
        print(f"[CRITICAL] Eroare API Messages: {str(e)}")
        return []

@router.delete("/api/sessions/{uuid}")
async def delete_chat_session(uuid: str, request: Request):
    user_id = request.session.get("user_id")
    company_id = request.session.get("company_id")
    try:
        db_path = get_db_path(user_id, company_id) 
        handler = SQLiteHandler(db_path)
        
        # Foreign Key cu CASCADE din handler se ocupă acum de ștergerea mesajelor
        rows_deleted = await handler.delete_conversation(uuid)
        
        if rows_deleted > 0:
            return {"status": "success", "message": f"Sesiunea {uuid} ștearsă (cu tot cu mesaje)."}
        else:
            return {"status": "error", "message": "Sesiunea nu a fost găsită."}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@router.patch("/api/sessions/{uuid}")
async def update_session(uuid: str, request: Request):
    try:
        user_id = request.session.get('user_id')
        company_id = request.session.get('company_id')
        db_path = get_db_path(user_id, company_id)
        
        if not db_path:
            return {"error": "Invalid DB path"}

        # Citim datele trimise din frontend (body-ul cererii JSON)
        data = await request.json()
        new_title = data.get("title")
        pinned = data.get("pinned")

        handler = SQLiteHandler(db_path)
        await handler.update_chat_meta(uuid, title=new_title, pinned=pinned)
        
        return {"status": "success"}
    except Exception as e:
        print(f"[CRITICAL] Eroare API Update Session: {str(e)}")
        return {"error": str(e)}, 500    
    