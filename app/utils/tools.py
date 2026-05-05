# tools.py - Definirea funcțiilor pentru uneltele disponibile în aplicație
import sys
import datetime
import pytz
import json
import httpx
import re
import asyncio
import contextvars
import numpy as np # Mai bine np
import pandas as pd
from sklearn.linear_model import LinearRegression
from bs4 import BeautifulSoup
from ddgs import DDGS
import logging

from app.utils.sqlite_handler import SQLiteHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Context injectat de backend la execute_tool (db user, conversație) — nu vine din LLM.
_tool_runtime_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "_tool_runtime_ctx", default=None
)

# --- UTILS ---

async def get_current_datetime():
    try:
        # Folosim locale pentru a avea numele zilei în română, 
        # sau formatăm direct dacă nu vrei să depinzi de setările sistemului.
        bucharest_timezone = pytz.timezone('Europe/Bucharest')
        now = datetime.datetime.now(bucharest_timezone)
        
        # %A returnează ziua săptămânii (ex: Saturday/Sâmbătă)
        # Am adăugat și un format mai "uman" la final
        return {
            "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S %Z%z"),
            "day_of_week": now.strftime("%A"),
            "display_format": now.strftime("%d %B %Y, %H:%M")
        }
    except Exception as e:
        return {"error": str(e)}

# --- WEATHER (ASYNCHRONOUS) ---

API_KEY = "a64230bd5eeac293c6064da395daefaf"  

async def get_current_weather(city: str):
    try:
        async with httpx.AsyncClient() as client:
            # 1️⃣ Geocodare
            geo_url = "http://api.openweathermap.org/geo/1.0/direct"
            geo_params = {"q": f"{city},RO", "limit": 1, "appid": API_KEY}
            
            geo_resp = await client.get(geo_url, params=geo_params, timeout=5.0)
            geo_data = geo_resp.json()

            if not geo_data:
                return {"status": "not_found", "query": city, "message": "Orașul nu a fost găsit."}

            lat = geo_data[0]["lat"]
            lon = geo_data[0]["lon"]

            # 2️⃣ One Call API
            weather_url = "https://api.openweathermap.org/data/3.0/onecall"
            weather_params = {
                "lat": lat, "lon": lon, "appid": API_KEY,
                "units": "metric", "lang": "ro",
                "exclude": "minutely,hourly,alerts"
            }
            
            weather_resp = await client.get(weather_url, params=weather_params, timeout=5.0)
            w_data = weather_resp.json()

            current = w_data.get("current", {})
            return {
                "status": "success",
                "query": city,
                "weather": current.get("weather", [{}])[0].get("description", "necunoscut"),
                "temperature": current.get("temp"),
                "feels_like": current.get("feels_like"),
                "humidity": current.get("humidity")
            }
    except Exception as e:
        return {"status": "error", "query": city, "message": str(e)}

# --- WEB SEARCH (ASYNCHRONOUS) ---

async def search_web(query: str):
    try:
        import datetime
        from ddgs import DDGS
        
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        # Curățăm doar anii vechi, nu adăugăm data forțat
        clean_query = query.lower().replace("2024", "").replace("2023", "").strip()

        with DDGS() as ddgs:
            # Lăsăm motorul să caute natural. 
            # DuckDuckGo va prioritiza oricum rezultatele relevante.
            raw_results = list(ddgs.text(clean_query, max_results=7))
            
        if not raw_results:
            return {"error": "Nu am găsit informații."}

        # Îi trimitem modelului ȘI data curentă ca metadatat, și rezultatele
        return {
            "current_system_date": today,
            "results": [
                {"title": r.get("title"), "body": r.get("body"), "url": r.get("href")} 
                for r in raw_results
            ]
        }
    except Exception as e:
        return {"error": str(e)}

# --- MATH ---

async def calculate(expression: str):
    """Evaluates a mathematical expression more safely and intuitively."""
    try:
        # 1. Curățăm spațiile și înlocuim ^ cu ** pentru ca 2^3 să devină 2**3
        safe_expr = expression.replace('^', '**')
        
        # 2. Permitem doar caractere matematice (cifre, operatori, paranteze, punct)
        # Asta previne injectarea de cod periculos
        allowed_chars = "0123456789+-*/().** "
        if not all(char in allowed_chars for char in safe_expr.replace(' ', '')):
             return {"error": "Caractere nepermise în expresie."}

        # 3. Folosim un dicționar limitat pentru eval (tot eval e, dar cu garduri înalte)
        result = eval(safe_expr, {"__builtins__": None}, {})
        
        # Rotunjim frumos la 4 zecimale să nu avem cârnați de cifre
        if isinstance(result, (int, float)):
            result = round(result, 4)
            
        return {"result": result}
    except Exception as e:
        return {"error": f"Calcul invalid: {str(e)}"}


async def save_user_memory(
    *,
    title: str,
    content: str,
    db_path: str | None = None,
    conversation_uuid: str | None = None,
):
    """
    Persistă o notă L0 în SQLite-ul userului. Apelat doar din backend (tool),
    cu db_path / conversation_uuid din contextul cererii, nu din argumentele LLM.
    """
    if not db_path:
        return {
            "status": "error",
            "message": "Memoria L0 e disponibilă doar pentru utilizatori autentificați.",
        }
    t = (title or "").strip()
    c = (content or "").strip()
    if not c:
        return {"status": "error", "message": "Parametrul content nu poate fi gol."}
    if not t:
        t = c[:80] + ("…" if len(c) > 80 else "")
    try:
        handler = SQLiteHandler(db_path)
        new_id = await handler.insert_memory_l0(
            title=t,
            content=c,
            source_conversation_uuid=conversation_uuid,
        )
        return {
            "status": "saved",
            "id": new_id,
            "message": "Informația a fost salvată în memoria L0. Utilizatorul o poate vedea și edita din Setări cont (chat) → Memorie salvată.",
        }
    except Exception as e:
        logger.error("save_user_memory: %s", e)
        return {"status": "error", "message": str(e)}


async def save_user_memory_tool(title: str, content: str):
    """Wrapper pentru LLM: citește db_path / conversation_uuid din contextul cererii."""
    ctx = _tool_runtime_ctx.get() or {}
    return await save_user_memory(
        title=title,
        content=content,
        db_path=ctx.get("db_path"),
        conversation_uuid=ctx.get("conversation_uuid"),
    )


async def execute_tool(tool_call, tool_context=None):
    """
    Execută uneltele declarate în TOOLS_DESCRIPTION / available_tools.
    Pentru unelte care au nevoie de context de sesiune, `tool_context` e setat pe durata apelului.
    """
    # 1. Extragere nume
    name = tool_call.get('function', {}).get('name')
    if not name:
        return {"error": "Numele funcției lipsește din tool_call"}

    # 2. Gestionare argumente (vLLM specific)
    args_raw = tool_call.get('function', {}).get('arguments', {})
    
    if isinstance(args_raw, str):
        try:
            # vLLM trimite uneori string-uri JSON complexe
            args = json.loads(args_raw)
        except json.JSONDecodeError as e:
            logger.error(f"Eroare parsare JSON pentru {name}: {e}")
            return {"error": f"Invalid JSON arguments: {str(e)}"}
    else:
        args = args_raw

    logger.info(f"🚀 [vLLM Tool] Executăm: {name} | Args: {args}")

    ctx_token = None
    if tool_context is not None:
        ctx_token = _tool_runtime_ctx.set(tool_context)

    try:
        if name in available_tools:
            try:
                result = await available_tools[name](**args)
                return result
            except TypeError as te:
                logger.error(f"Argumente invalide pentru {name}: {te}")
                return {"error": f"Argument mismatch: {str(te)}"}
            except Exception as e:
                logger.error(f"Eroare internă la {name}: {e}")
                return {"error": str(e)}

        logger.warning(f"⚠️ Unealta {name} nu este definită în available_tools.")
        return {"error": f"Tool {name} not found in S366 AI registry"}
    finally:
        if ctx_token is not None:
            _tool_runtime_ctx.reset(ctx_token)
    

TOOLS_DESCRIPTION = [
            {
                "type": "function",
                "function": {
                    "name": "get_current_datetime",
                    "description": "Returns the current date and time in the Bucharest timezone.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "Return the current weather for a given city.",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Perform a web search for the given query and return structured results. Always include for each result: 'title', 'snippet', and 'url'. Never omit the URL. The tool response must be a JSON object containing a 'results' array.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query text (e.g., 'latest news about AI')."
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Evaluates a simple mathematical expression. Use this tool for any mathematical calculations, such as 'what is 2 + 2?', 'solve x^2 + 8x - 25 = 0', etc.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": { "type": "string", "description": "The mathematical expression to evaluate." }
                        },
                        "required": ["expression"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "save_user_memory",
                    "description": (
                        "Salvează o informație sau idee pe care utilizatorul ți-o cere EXPLICIT să o reții "
                        "(ex: „salvează asta”, „notează că…”, „ține minte…”). Nu apela fără cerere clară. "
                        "Titlu scurt (etichetă), content = textul complet de reținut. Utilizatorul le gestionează din "
                        "Setări cont (chat) → Memorie salvată."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Etichetă scurtă (ex: „Data nașterii”, „Stack proiect X”).",
                            },
                            "content": {
                                "type": "string",
                                "description": "Textul exact de salvat (fapte, formulări, idei).",
                            },
                        },
                        "required": ["title", "content"],
                    },
                },
            },
        ]
# --- TOOL MAPPING ---

available_tools = {
    "get_current_datetime": get_current_datetime,
    "get_current_weather": get_current_weather,
    "search_web": search_web,
    "calculate": calculate,
    "save_user_memory": save_user_memory_tool,
}