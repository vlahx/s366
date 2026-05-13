# Rute HTTP pentru clienți externi (ex. aplicația Production) — autentificare cu api_key din companies.
# Răspunsul la chat e același flux NDJSON ca /chat/send (conținut JSON pe linii), compatibil cu logica din chat_api.js / streaming.
import base64
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.utils.payload_builder import build_llm_payload
from app.routes.chat import _sanitize_images_b64

router = APIRouter()


def _extract_api_key(request: Request) -> Optional[str]:
    h = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if h and h.strip():
        return h.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _row_to_dict(row: Any) -> Optional[dict]:
    if row is None:
        return None
    return dict(row)


@router.get("/whoami")
async def api_whoami(request: Request):
    """Verificare rapidă a cheii (fără consum LLM)."""
    api_key = _extract_api_key(request)
    svc = request.app.state.api_service
    company = await svc.validate_api_key(api_key or "")
    if not company:
        raise HTTPException(status_code=401, detail="Cheie API invalidă sau lipsă.")
    return {
        "ok": True,
        "company_id": company["company_id"],
        "company_name": company.get("company_name"),
        "cui": company.get("cui"),
    }


@router.post("/chat/send")
async def api_chat_send(request: Request):
    """
    Chat cu același LLM ca interfața web, în contextul firmei asociate cheii API.

    Headere: `X-API-Key: <cheie>` sau `Authorization: Bearer <cheie>`

    Body JSON (similar /chat/send):
    - `message` (string)
    - `conversation_uuid` (opțional)
    - `conversation_history` (opțional) — doar dacă NU trimiți `external_client_id` (mod „guest”).
    - `images_b64` (opțional) — listă sau string base64 / data URL
    - `audio_b64` (opțional)
    - `external_client_id` (opțional) — ID stabil client (ex. telefon / id stație); creează/caută user în firmă și folosește istoric SQLite.
    - `fingerprint` (opțional) — supliment la external_client_id
    """
    api_key = _extract_api_key(request)
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Lipsește cheia API (X-API-Key sau Authorization: Bearer).",
        )
    svc = request.app.state.api_service
    company = await svc.validate_api_key(api_key)
    if not company:
        raise HTTPException(status_code=401, detail="Cheie API invalidă.")

    llm_service = request.app.state.llm_service

    data = await request.json()
    user_message = data.get("message")
    audio_b64 = data.get("audio_b64")
    images_b64 = _sanitize_images_b64(data.get("images_b64"))
    conv_uuid = data.get("conversation_uuid") or str(uuid.uuid4())
    client_history = data.get("conversation_history")
    external_client_id = (data.get("external_client_id") or "").strip() or None
    fingerprint = (data.get("fingerprint") or "").strip() or None

    company_id = company["company_id"]
    company_cui = company.get("cui")
    company_name = company.get("company_name")

    user_id = None
    user_firstname = "API"
    user_lastname = ""
    user_role = "user"

    if external_client_id:
        urow = await svc.get_or_create_external_user(company, external_client_id, fingerprint)
        if not urow:
            raise HTTPException(status_code=500, detail="Nu s-a putut rezolva utilizatorul extern.")
        ud = _row_to_dict(urow)
        user_id = ud.get("id")
        user_firstname = (ud.get("firstname") or "Client").strip() or "Client"
        user_lastname = (ud.get("lastname") or "").strip()
        user_role = (ud.get("role") or "external").strip() or "external"
        client_history = None
    elif client_history and not isinstance(client_history, list):
        client_history = None

    payload = await build_llm_payload(
        user_message=user_message if not audio_b64 else "",
        user_id=user_id,
        user_role=user_role,
        user_firstname=user_firstname,
        user_lastname=user_lastname,
        company_id=company_id,
        company_cui=company_cui,
        company_name=company_name,
        conversation_uuid=conv_uuid,
        client_messages=client_history,
        image_base64_list=images_b64 if images_b64 else None,
    )

    if audio_b64:
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="audio_b64 nu e base64 valid.")
        gen = llm_service.get_voice_response(audio_bytes, payload)
    else:
        gen = llm_service.get_internal_response(payload)

    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "X-Conversation-UUID": conv_uuid,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
