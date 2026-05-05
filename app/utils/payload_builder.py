# app/utils/payload_builder.py
from datetime import datetime
import pytz
#from urllib import request
from app.utils.db_helpers import get_db_path
from app.utils.sqlite_handler import SQLiteHandler
from app.utils.db_prompts import get_prompts_json
from app.utils.db_rags import get_rag_data
import os
import sys
import json

from app.models.sqlite_company_model import get_company_settings
from app.utils.text_cleaner import assistant_bubble_to_llm_text

# Sufix lipit mereu DUPĂ conținutul din general_prompt.txt (nu înlocuiește fișierul de pe disc).
_GENERAL_PROMPT_TOOLS_SUFFIX = """
### Function calling (unelte disponibile)
- get_current_datetime — dată/oră (București).
- get_current_weather — vremea pentru un oraș (`city`).
- search_web — căutare web (`query`).
- calculate — expresie matematică simplă (`expression`).
- save_user_memory — salvează în memoria L0 a userului (`title`, `content`); **doar** dacă cere explicit (ex. „salvează asta”, „ține minte…”). Poate edita șterge din Setări cont (chat) → Memorie salvată.
"""

async def build_llm_payload(user_message, conversation_uuid=None, user_id=None, user_role=None, user_lastname=None, user_firstname=None,
                      company_id=None, company_cui=None, company_name=None, client_messages=None):


    user_id = user_id 
    user_role = user_role 
    user_lastname = user_lastname
    user_firstname = user_firstname    
    company_id = company_id
    company_cui = company_cui 
    company_name = company_name 
    

    #if not company_cui:
    #    print("EROARE: company_cui lipseste din sesiune sau argumente.", file=sys.stderr)
    #    return None

    # Setați timezone-ul pentru România
    tz_ro = pytz.timezone('Europe/Bucharest')
    now = datetime.now(tz_ro)

    # Mapare pentru zilele săptămânii în română (opțional, dar recomandat pentru prompt)
    zile_saptamana = {
        "Monday": "Luni",
        "Tuesday": "Marți",
        "Wednesday": "Miercuri",
        "Thursday": "Joi",
        "Friday": "Vineri",
        "Saturday": "Sâmbătă",
        "Sunday": "Duminică"
    }

    ziua_nume = zile_saptamana.get(now.strftime("%A"), now.strftime("%A"))

    # Formatăm data finală: "Marți, 24-03-2026"
    data_curenta = f"{ziua_nume}, {now.strftime('%d-%m-%Y')}"
    ora_curenta = now.strftime("%H:%M")

    print(f"Data: {data_curenta} | Ora: {ora_curenta}")

    # --- Istoricul conversației (SQLite) ---
    conversation_history = []
    
    # Aici e cheia: get_db_path va folosi acum noua logică cu 2 IF-uri
    # Dacă e standalone (fără company_id), va returna calea către /standalone_users/
    db_path = get_db_path(user_id=user_id, company_id=company_id)
    
    if db_path and conversation_uuid:
        # Verificăm dacă fișierul chiar există înainte să încercăm să citim
        # Asta previne erori inutile dacă e prima conversație a userului
        if os.path.exists(db_path):
            try:
                db_handler = SQLiteHandler(db_path)
                raw_history = await db_handler.get_conversation(conversation_uuid)
                
                if raw_history:
                    for msg in raw_history:
                        role = msg.get('sender', 'user')
                        content = msg.get('message', '') or ''
                        if role == 'assistant':
                            content = assistant_bubble_to_llm_text(content)
                        conversation_history.append({
                            'role': role,
                            'content': content
                        })
                # print(f"[DEBUG] Istoric încărcat din: {db_path}", file=sys.stderr)
            except Exception as e:
                print(f"EROARE la citirea istoricului din {db_path}: {e}", file=sys.stderr)
        else:
            print(f"[DEBUG] Fișier DB inexistent (Prima conversație?): {db_path}", file=sys.stderr)

    elif client_messages and isinstance(client_messages, list):
        # Vizitator fără SQLite: istoric trimis de client (LocalStorage), validat minimal
        for msg in client_messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            conversation_history.append({"role": role, "content": content})

    # Adaugă mesajul curent al userului
    conversation_history.append({"role": "user", "content": user_message})
##########################configu ma-sii
    cui = company_cui
    settings=await get_company_settings(cui)
    rag_temperature = settings.get("rag_temperature", "")
    rag_top_k = settings.get("rag_top_k", "") #folosit in rag deja
    rag_threshold = settings.get("rag_threshold", "") # folosit in rag deja
    

############################
    # --- Prompturi generale și specifice companiei ---
    base_path = "/companies_data/general/prompts"
    file_name = "general_prompt.txt"
    env_override = os.environ.get("GENERAL_PROMPT_PATH")
    general_prompt_path = env_override if env_override and os.path.isfile(env_override) else os.path.join(base_path, file_name)

    try:
        with open(general_prompt_path, "r", encoding="utf-8") as f:
            general_prompt = f.read()
        
        # 🛡️ Fix: Ne asigurăm că avem string-uri, nu None
        # Dacă variabila e None, va folosi un string gol sau un nume default
        safe_firstname = str(user_firstname or "Vizitator")
        safe_company = str(company_name or "Companie")

        general_prompt = general_prompt.replace("{{firstname}}", safe_firstname)
        general_prompt = general_prompt.replace("{{company_name}}", safe_company)
        general_prompt = general_prompt.replace("{{current_time}}", ora_curenta)
        general_prompt = general_prompt.replace("{{current_date}}", data_curenta)
        
    except Exception as e:
        # Aici va intra dacă fișierul nu există fizic la acea cale
        print(f"EROARE la citirea general_prompt.txt: {e}", file=sys.stderr)
        general_prompt = "Ești un asistent util." # Un fallback minim ca să nu plece gol

    general_prompt = general_prompt.rstrip() + _GENERAL_PROMPT_TOOLS_SUFFIX

    # Prompturile companiei
    # 1. Extragerea datelor cu Try/Except (Păstrăm siguranța)
    try:
        company_prompts = await get_prompts_json(cui=company_cui)
        # Extragem textul structurat pe care l-am pregătit în db_prompts.py
        company_prompt_text = company_prompts.get("company_prompt", "")
    except Exception as e:
        print(f"❌ EROARE critică la extragerea prompturilor (CUI: {company_cui}): {e}", file=sys.stderr)
        company_prompt_text = ""

    # 2. Asamblarea inteligentă (Dacă avem prompte, le punem sub header)
    if company_prompt_text:
        # Îi dăm AI-ului un indiciu clar că aici începe specificul firmei
        business_context = f"\n\n### CONTEXT SPECIFIC COMPANIE ###\n{company_prompt_text}\n################################"
    else:
        business_context = ""

    # 3. Combinarea finală
    system_prompt_combined = f"{general_prompt}{business_context}"

    # --- Memorie L0 (aceeași SQLite ca mesajele) — doar utilizatori autentificați ---
    memory_instructions = """
### MEMORIE L0 (persistantă)
În blocul următor găsești informații pe care utilizatorul le-a salvat explicit sau le-a lăsat vizibile în Setări.
- Folosește-le ca sursă de adevăr când sunt relevante pentru întrebarea curentă.
- Dacă utilizatorul îți cere clar să salvezi / să reții / să notezi o informație sau idee, apelează tool-ul **save_user_memory** cu un titlu scurt și câmpul **content** cu textul complet de păstrat. Confirmă-i scurt că a fost salvată.
- Nu salva nimic din proprie inițiativă fără cerere explicită.
"""
    memory_block = ""
    if user_id and db_path and os.path.exists(db_path):
        try:
            db_handler = SQLiteHandler(db_path)
            items = await db_handler.list_memory_l0(limit=40)

            def _one_line(s: str, max_len: int) -> str:
                x = " ".join((s or "").split())
                if len(x) <= max_len:
                    return x
                return x[: max_len - 1] + "…"

            if items:
                lines = []
                for it in items:
                    tid = it.get("id")
                    tit = _one_line(str(it.get("title") or ""), 120)
                    body = _one_line(str(it.get("content") or ""), 400)
                    if tit and body:
                        lines.append(f"- [id={tid}] {tit}: {body}")
                    elif body:
                        lines.append(f"- [id={tid}] {body}")
                memory_block = (
                    memory_instructions
                    + "\n### DATE SALVATE (L0)\n"
                    + "\n".join(lines)
                    + "\n"
                )
            else:
                memory_block = (
                    memory_instructions
                    + "\n### DATE SALVATE (L0)\n(nicio înregistrare încă)\n"
                )
        except Exception as e:
            print(f"EROARE la citirea memory_l0: {e}", file=sys.stderr)

    system_prompt_combined = f"{system_prompt_combined}{memory_block}"

    # --- RAG relevant ---
    try:
        rag_text = await get_rag_data(
        query_text=user_message, 
        cui=company_cui, 
        top_k=int(settings.get("rag_top_k", 5)), 
        threshold=float(settings.get("rag_threshold", 0.6))
    )
        
        # Debug opțional să vezi ce context trimiți la Ollama
        if rag_text:
            print(f"✅ [RAG] Context extras: {len(rag_text)} caractere (K={int(settings.get('rag_top_k', 5))}, Threshold={float(settings.get('rag_threshold', 0.6))}).")
        else:
            print(f"ℹ️ [RAG] Niciun context peste threshold-ul {float(settings.get('rag_threshold', 0.6))}.")

    except Exception as e:
        print(f"❌ EROARE la extragerea RAG: {e}", file=sys.stderr)
        rag_text = ""
    current_datetime = datetime.now(tz_ro).isoformat()
    # --- Construim payload ---
    payload = {
        "user": {
            "id": user_id,
            "role": user_role,
            "firstname": user_firstname,
            "lastname": user_lastname
        },
        "company": {
            "id": company_id,
            "cui": company_cui,
            "name": company_name
        },
        "conversation": {
            "messages": conversation_history,
            "datetime": current_datetime,
            "uuid": conversation_uuid
        },
        "context": {
            "system_prompt": system_prompt_combined,
            "rag_data": rag_text
        },
        "user_input": user_message
    }
    # Diagnostic: decomentează temporar ca să vezi tot payloadul trimis spre LLM (log greu, poate conține date sensibile).
    # print(f"[DEBUG] Payload trimis catre Ollama: {payload}", file=sys.stderr)
    return payload
