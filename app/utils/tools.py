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
from urllib.parse import urlparse
import ipaddress
import socket

from app.utils.sqlite_handler import SQLiteHandler
from app.utils.db_news import ingest_wordpress_news, search_news

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

# --- WEB SCRAPE (ASYNCHRONOUS) ---

def _is_private_host(hostname: str) -> bool:
    """
    SSRF guard: blochează localhost / IP-uri private / link-local / loopback.
    Permite doar host-uri publice.
    """
    if not hostname:
        return True
    h = hostname.strip().lower()
    if h in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        # Dacă e IP direct
        ip = ipaddress.ip_address(h)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        )
    except ValueError:
        pass

    # Dacă e domeniu, încercăm să-l rezolvăm și blocăm dacă dă IP privat
    try:
        infos = socket.getaddrinfo(h, None)
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_multicast
                    or ip.is_reserved
                ):
                    return True
            except ValueError:
                continue
    except Exception:
        # dacă nu poate rezolva, îl considerăm nesigur
        return True
    return False


async def scrape_url(
    url: str,
    selector: str | None = None,
    max_chars: int = 20000,
    timeout_s: float = 20.0,
):
    """
    Descarcă o pagină HTML și întoarce text curățat (pentru LLM).
    - selector: CSS selector opțional (ex: 'table', '.content', '#main')
    - max_chars: limită pentru content ca să nu explodeze contextul
    """
    u = (url or "").strip()
    if not u:
        return {"error": "Parametrul url este obligatoriu."}
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        return {"error": "URL invalid. Accept doar http/https."}
    if _is_private_host(parsed.hostname or ""):
        return {"error": "Host interzis (protecție SSRF)."}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.7",
    }

    try:
        async with httpx.AsyncClient(
            timeout=float(timeout_s),
            headers=headers,
            follow_redirects=True,
        ) as client:
            resp = await client.get(u)
            ct = (resp.headers.get("content-type") or "").lower()
            if resp.status_code >= 400:
                return {"error": f"HTTP {resp.status_code}", "url": str(resp.url)}
            if "text/html" not in ct and "application/xhtml+xml" not in ct:
                # unele site-uri omit headerul corect; permitem dacă pare HTML
                sample = (resp.text or "")[:500].lower()
                if "<html" not in sample and "<!doctype" not in sample:
                    return {"error": "Conținutul nu pare HTML.", "content_type": ct, "url": str(resp.url)}

            html_text = resp.text or ""

        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        chosen = soup
        sel = (selector or "").strip()
        if sel:
            node = soup.select_one(sel)
            if node is not None:
                chosen = node

        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        text = chosen.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if max_chars and len(text) > int(max_chars):
            text = text[: int(max_chars)] + "…"

        return {
            "status": "success",
            "final_url": str(parsed.geturl()),
            "title": title,
            "selector_used": sel or None,
            "content": text,
            "content_length": len(text),
        }
    except Exception as e:
        return {"error": str(e)}


async def ingest_wp_news(
    base_url: str,
    max_items: int = 40,
):
    """
    Ingestie știri (WordPress) în layer separat (news_items), cu embeddings pe summary.
    Folosește contextul companiei (company_cui) injectat de backend.
    """
    ctx = _tool_runtime_ctx.get() or {}
    cui = (ctx.get("company_cui") or "").strip()
    if not cui:
        return {"status": "error", "message": "Tool disponibil doar în context de companie (lipsă company_cui)."}
    return await ingest_wordpress_news(cui, base_url=base_url, max_items=int(max_items))


async def search_company_news(
    query: str,
    days: int = 30,
    top_k: int = 5,
    threshold: float = 0.35,
):
    """
    Căutare semantică în știrile companiei (news_items) — nu poluează RAG documents/chunks.
    """
    ctx = _tool_runtime_ctx.get() or {}
    cui = (ctx.get("company_cui") or "").strip()
    if not cui:
        return {"status": "error", "message": "Tool disponibil doar în context de companie (lipsă company_cui)."}
    return await search_news(
        cui,
        query=query,
        days=int(days),
        top_k=int(top_k),
        threshold=float(threshold),
    )

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
                    "name": "scrape_url",
                    "description": (
                        "Fetch a web page (HTML) and return cleaned text content for analysis. "
                        "Use after search_web when you need the actual page text or tables. "
                        "Provide 'url'. Optional 'selector' (CSS) to target a section. "
                        "Returns JSON with title and content."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "HTTP/HTTPS URL to fetch."},
                            "selector": {
                                "type": "string",
                                "description": "Optional CSS selector to extract a section (e.g. 'table', '#main').",
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": "Max characters of extracted text to return (default 20000).",
                            },
                            "timeout_s": {
                                "type": "number",
                                "description": "Request timeout seconds (default 20).",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ingest_wp_news",
                    "description": (
                        "Ingest latest WordPress posts into the company's News layer (not RAG). "
                        "Use when the user asks to sync a news site/feed for later Q&A. "
                        "Provide base_url (site root, e.g. https://example.com)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "base_url": {"type": "string", "description": "WordPress site base URL."},
                            "max_items": {
                                "type": "integer",
                                "description": "How many recent posts to ingest (default 40).",
                            },
                        },
                        "required": ["base_url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_company_news",
                    "description": (
                        "Semantic search in the company's ingested News layer. "
                        "Returns a small list of matching articles with title, date, score and summary."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "days": {"type": "integer", "description": "Recency window in days (default 30)."},
                            "top_k": {"type": "integer", "description": "Max results (default 5)."},
                            "threshold": {"type": "number", "description": "Similarity threshold (default 0.35)."},
                        },
                        "required": ["query"],
                    },
                },
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
    "scrape_url": scrape_url,
    "ingest_wp_news": ingest_wp_news,
    "search_company_news": search_company_news,
    "calculate": calculate,
    "save_user_memory": save_user_memory_tool,
}