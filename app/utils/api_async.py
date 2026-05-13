import httpx
import sys
import logging
import json
import asyncio
import datetime
from typing import List, Optional
from fastapi import HTTPException
import uuid
import base64
from app.models.sqlite_company_model import get_company_settings
from app.utils.tools import available_tools, execute_tool, TOOLS_DESCRIPTION
from app.utils.ollama_async import OllamaAsyncAPI
#from app.utils.vllm_async import VLLMAsyncAPI
from app.utils.payload_builder import build_llm_payload
from app.utils.db_helpers import get_db_path
from app.utils.sqlite_handler import SQLiteHandler
from app.utils.tts import generate_speech_async
from app.utils.text_cleaner import sanitize_llm_text
from app.utils.stt import transcribe_audio_async
from app.utils.text_cleaner import clean_markdown_to_html
from app.models.sqlite_model import fetch_one, execute_insert

# Configurăm logging-ul să vedem ce se întâmplă în container
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMServiceAsync:
    def __init__(self):
        self.model_name = "qwen3.5:9b"
        self.llm_api_async = OllamaAsyncAPI()
        self.tools_description = TOOLS_DESCRIPTION
    
    async def get_internal_response(self, payload: dict):
        user_data = payload.get('user', {})
        user_id = user_data.get('id')
        company_id = payload.get('company', {}).get('id')
        company_cui = payload.get('company', {}).get('cui')
        conv_uuid = payload.get('conversation', {}).get('uuid')
        
        history = payload.get('conversation', {}).get('messages', [])
        last_user = history[-1] if history and history[-1].get('role') == 'user' else None
        user_message = ""
        if last_user:
            c = last_user.get('content', '')
            user_message = c if isinstance(c, str) else ''
            if last_user.get('images'):
                user_message = (user_message or "(imagine)").strip()
                user_message = f"{user_message} [+{len(last_user['images'])} imagini]"
        system_prompt = payload.get('context', {}).get('system_prompt', '')
        rag_data = payload.get('context', {}).get('rag_data', '')

        settings = await get_company_settings(company_cui) or {}

        db_path_tools = get_db_path(user_id=user_id, company_id=company_id)
        tool_context = {
            "db_path": db_path_tools if db_path_tools else None,
            "conversation_uuid": conv_uuid,
            "company_cui": company_cui,
            "company_id": company_id,
        }
        tools_for_request = self.tools_description
        if not user_id or not tool_context.get("db_path"):
            tools_for_request = [
                t
                for t in self.tools_description
                if (t.get("function") or {}).get("name") != "save_user_memory"
            ]

        # rag_temperature în DB e folosită și la RAG; pentru chat evităm valori foarte mici (ex. 0.1) care destabilizează qwen3.5 în Ollama.
        if "llm_temperature" in settings:
            chat_temp = float(settings["llm_temperature"])
        else:
            chat_temp = max(float(settings.get("rag_temperature", 0.55)), 0.45)
        llm_options = {
            "temperature": chat_temp,
            # qwen3.5:9b suportă context mai mare; dăm default 16384 ca să evităm truncări
            # când tool-urile (scrape_url) întorc mult text.
            "num_ctx": int(settings.get("rag_num_ctx", 16384)),
            "repeat_penalty": float(settings.get("rag_repeat_penalty", 1.15)),
        }

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        
        full_messages.extend(history)

        if rag_data:
            for i in range(len(full_messages) - 1, -1, -1):
                if full_messages[i]['role'] == 'user':
                    msg = full_messages[i]
                    cur = msg.get('content', '')
                    suffix = f"\n\nContext relevant:\n{rag_data}"
                    if isinstance(cur, str):
                        msg['content'] = cur + suffix
                    break

        full_ai_response = ""
        max_iterations = 5  

        try:
            for iteration in range(max_iterations):
                tool_calls_accumulator = {}
                received_tool_calls = False
                current_turn_content = ""

                # --- APEL LLM STREAM (Versiunea cu Robinet) ---
                buffer_text = "" # Buffer special pentru Markdown -> HTML
        
                async for chunk in self.llm_api_async.chat_stream(
                    model_name=self.model_name,
                    messages=full_messages,
                    tools=tools_for_request,
                    options=llm_options
                ):
                    message = chunk.get('message', {})
            
                    if 'content' in message and message['content']:
                        content = message['content']
                        current_turn_content += content
                        full_ai_response += content
                        # Trimitem BRUT, fără conversie HTML în timpul stream-ului
                        yield json.dumps({"content": content}) + "\n"
                
                        
                    
                    if 'tool_calls' in message:
                        received_tool_calls = True
                        for tc in message['tool_calls']:
                            idx = tc.get('index', 0)
                            if idx not in tool_calls_accumulator:
                                tool_calls_accumulator[idx] = tc
                            else:
                                # Verificăm dacă avem funcție și argumente de acumulat
                                if 'function' in tc and 'arguments' in tc['function']:
                                    new_args = tc['function']['arguments']
                                    current_args = tool_calls_accumulator[idx]['function']['arguments']

                                    # CAZUL 1: Sunt string-uri (vLLM style / streaming pur)
                                    if isinstance(current_args, str) and isinstance(new_args, str):
                                        tool_calls_accumulator[idx]['function']['arguments'] += new_args
                
                                    # CAZUL 2: Sunt dicționare (Ollama style)
                                    elif isinstance(current_args, dict) and isinstance(new_args, dict):
                                        tool_calls_accumulator[idx]['function']['arguments'].update(new_args)
                
                                    # CAZUL 3: Backup (în caz că Ollama trimite un dict peste un string gol)
                                    else:
                                        tool_calls_accumulator[idx]['function']['arguments'] = new_args


                # Dacă nu avem tool calls în tura asta, am terminat procesarea
                if not received_tool_calls:
                    break

                # --- EXECUȚIE TOOLS ---
                final_tool_calls = list(tool_calls_accumulator.values())
                
                # Înregistrăm cererea asistentului în istoric înainte de rezultate
                assistant_history_msg = {"role": "assistant", "tool_calls": final_tool_calls}
                if current_turn_content:
                    assistant_history_msg["content"] = current_turn_content
                
                full_messages.append(assistant_history_msg)

                for tool_call in final_tool_calls:
                    # Rulăm funcția din tools.py
                    result = await execute_tool(tool_call, tool_context)
                    
                    # Adăugăm rezultatul în context pentru următoarea iterație
                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get('id'),
                        "name": tool_call['function']['name'],
                        "content": json.dumps(result)
                    })
                
                # Bucla merge la următoarea iterație (vLLM va vedea rezultatele și va decide)

        finally:
            # --- SALVARE ÎN BAZA DE DATE (SQLite pe NVMe) ---
            db_path = get_db_path(user_id=user_id, company_id=company_id)
            if db_path and conv_uuid:
                try:
                    handler = SQLiteHandler(db_path)
                    await handler.save_chat_turn(conv_uuid, user_message, full_ai_response)
                except Exception as e:
                    print(f"EROARE la salvare: {e}", file=sys.stderr)


   


    async def get_voice_response(self, audio_data: bytes, payload: dict):
        # 1. STT: Whisper face text din audio
        user_text = await transcribe_audio_async(audio_data)
        
        if not user_text:
            yield json.dumps({"error": "Nu am înțeles."}) + "\n"
            return

        yield json.dumps({"user_transcription": user_text}) + "\n"
        payload['conversation']['messages'].append({"role": "user", "content": user_text})

        # 2. GENERARE TEXT
        full_ai_text = ""
        async for chunk in self.get_internal_response(payload):
            yield chunk + "\n"
            try:
                data = json.loads(chunk)
                if "content" in data:
                    full_ai_text += data["content"]
            except:
                continue

        
        if full_ai_text:
            
            clean_voice_text = sanitize_llm_text(full_ai_text)
            
            # Inițializăm un buffer de BYTES (nu string!)
            full_audio_bytes = b""
            
            # Consumăm generatorul Piper
            async for audio_chunk in generate_speech_async(clean_voice_text):
                # audio_chunk vine ca bytes, deci folosim += pe bytes
                full_audio_bytes += audio_chunk
            
            # TRANSFORMĂM ÎN BASE64 LA FINAL
            if full_audio_bytes:
                # Transformăm bytes în string base64
                audio_b64 = base64.b64encode(full_audio_bytes).decode('utf-8')
                yield json.dumps({"audio_payload": audio_b64}) + "\n"
    
class APIServiceAsync:
    """Servicii pentru integrări externe: validare `api_key` (tabel companies, SQLite) + user API."""

    async def validate_api_key(self, api_key: str):
        if not api_key or not str(api_key).strip():
            return None
        row = await fetch_one(
            """
            SELECT company_id, name AS company_name, cui, folder_path, slug, status
            FROM companies
            WHERE api_key = ?
            LIMIT 1
            """,
            (str(api_key).strip(),),
        )
        if not row:
            return None
        return dict(row)

    async def get_or_create_external_user(
        self, company: dict, phone_number: str, fingerprint: str | None = None
    ):
        """
        Utilizator legat de firmă pentru clienți fără login web (ex. stație Production).
        `phone_number` e folosit ca valoare unică în `users.email` (convenție veche din cod).
        """
        cid = company.get("company_id")
        if cid is None or not str(phone_number or "").strip():
            return None
        phone_number = str(phone_number).strip()

        row = await fetch_one(
            """
            SELECT * FROM users
            WHERE email = ? AND company_id = ?
            LIMIT 1
            """,
            (phone_number, cid),
        )
        if row:
            return row

        try:
            uid = await execute_insert(
                """
                INSERT INTO users (role, company_id, email, fingerprint, provider, is_visible)
                VALUES (?, ?, ?, ?, 'api_external', 0)
                """,
                ("external", cid, phone_number, fingerprint),
            )
        except Exception as e:
            logger.error("Eroare la creare user extern: %s", e)
            row = await fetch_one(
                """
                SELECT * FROM users
                WHERE email = ? AND company_id = ?
                LIMIT 1
                """,
                (phone_number, cid),
            )
            return row

        return await fetch_one("SELECT * FROM users WHERE id = ?", (uid,))