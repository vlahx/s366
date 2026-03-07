from pyexpat.errors import messages
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

from app.utils.tools import available_tools, execute_tool, TOOLS_DESCRIPTION
from app.utils.ollama_async import OllamaAsyncAPI
from app.utils.payload_builder import build_llm_payload
from app.utils.db_helpers import get_db_path
from app.utils.sqlite_handler import SQLiteHandler
from app.utils.tts import generate_speech_async
from app.utils.text_cleaner import sanitize_llm_text
from app.utils.stt import transcribe_audio_async

# Configurăm logging-ul să vedem ce se întâmplă în container
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMServiceAsync:
    def __init__(self):
       
        self.model_name = "cnshenyang/qwen3-nothink:14b" 
        self.llm_api_async = OllamaAsyncAPI()
        self.tools_description = TOOLS_DESCRIPTION
    
    async def get_internal_response(self, payload: dict):
        user_data = payload.get('user', {})
        user_id = user_data.get('id')
        company_id = payload.get('company', {}).get('id')
        conv_uuid = payload.get('conversation', {}).get('uuid')
        
        history = payload.get('conversation', {}).get('messages', [])
        user_message = history[-1]['content'] if history and history[-1]['role'] == 'user' else ""
        system_prompt = payload.get('context', {}).get('system_prompt', '')
        rag_data = payload.get('context', {}).get('rag_data', '')

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        
        full_messages.extend(history)

        # Injectăm RAG-ul (SQLite-ul ăla nou de l-am făcut)
        if rag_data:
            for i in range(len(full_messages) - 1, -1, -1):
                if full_messages[i]['role'] == 'user':
                    full_messages[i]['content'] += f"\n\nContext relevant:\n{rag_data}"
                    break

        full_ai_response = ""
        tool_calls = []

        try:
            # --- 1. APEL STREAM ---
            async for chunk in self.llm_api_async.chat_stream(
                self.model_name, full_messages, self.tools_description
            ):
                message = chunk.get('message', {})
                
                # Verificăm dacă primim conținut text
                if 'content' in message:
                    content = message['content']
                    full_ai_response += content
                    yield json.dumps({"content": content}) + "\n"

                # Verificăm dacă primim Tool Calls (Ollama le poate trimite în chunk)
                if 'tool_calls' in message:
                    tool_calls.extend(message['tool_calls'])

            # --- 2. EXECUȚIE TOOLS (Dacă LLM-ul a cerut ceva) ---
            if tool_calls:
                # 1. Adăugăm mesajul asistentului cu intenția de tool în istoric
                full_messages.append({"role": "assistant", "tool_calls": tool_calls})

                for tool_call in tool_calls:
                    # 2. Executăm unealta (funcția ta de încredere)
                    result = await execute_tool(tool_call)
                    
                    # 3. Adăugăm rezultatul în istoric pentru runda a doua
                    full_messages.append({
                        "role": "tool",
                        "content": json.dumps(result),
                        "name": tool_call['function']['name']
                    })

                # --- 3. AL DOILEA APEL (Finalizarea după Tool) ---
                # Folosim generic llm_api_async și iterăm prin stream (fără await pe generator)
                async for final_chunk in self.llm_api_async.chat_stream(self.model_name, full_messages, self.tools_description):
                    # Verificăm dacă bucata de stream conține text
                    message = final_chunk.get('message', {})
                    if 'content' in message:
                        content = message['content']
                        full_ai_response += content
                        # Trimitem imediat către client
                        yield json.dumps({"content": content}) + "\n"

        finally:
            # --- 4. Salvare Finală în SQLite (Păstrat intact) ---
            db_path = get_db_path(user_id=user_id, company_id=company_id)
            if db_path and conv_uuid:
                try:
                    handler = SQLiteHandler(db_path)
                    handler.force_init_db()
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
    """Servicii de bază de date - VARIANTĂ ASINCRONĂ"""

    async def validate_api_key(self, api_key: str):
        if not api_key: return None
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(dictionary=True) as cursor:
                await cursor.execute("""
                    SELECT company_id, name AS company_name, cui, folder_path
                    FROM companies WHERE api_key = %s
                """, (api_key,))
                return await cursor.fetchone()

    async def get_or_create_external_user(self, company: dict, phone_number: str, fingerprint: str = None):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(dictionary=True) as cursor:
                # 1. Căutăm
                await cursor.execute("""
                    SELECT u.*, c.company_id, c.name, c.cui, c.folder_path
                    FROM users u JOIN companies c ON u.company_id = c.company_id
                    WHERE u.email = %s AND u.company_id = %s
                """, (phone_number, company["company_id"]))
                user = await cursor.fetchone()
                if user: return user

                # 2. Creăm
                try:
                    await cursor.execute("""
                        INSERT INTO users (role, company_id, email, fingerprint, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                    """, ("external", company["company_id"], phone_number, fingerprint, datetime.datetime.now()))
                    await conn.commit()
                    user_id = cursor.lastrowid
                    
                    await cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                    return await cursor.fetchone()
                except Exception as e:
                    logger.error(f"Race condition la create user: {e}")
                    return None