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

async def build_llm_payload(user_message, conversation_uuid=None, user_id=None, user_role=None,user_lastname=None, user_firstname=None,
                      company_id=None, company_cui=None, company_name=None):

    # Fallback la session dacă nu sunt transmise argumente
    user_id = user_id 
    user_firstname = user_firstname 
    user_lastname = user_lastname
    user_role = user_role 
    company_cui = company_cui 
    company_name = company_name 
    company_id = company_id

    #if not company_cui:
    #    print("EROARE: company_cui lipseste din sesiune sau argumente.", file=sys.stderr)
    #    return None

    # Data / ora
    current_datetime = datetime.now().isoformat()
    tz_ro = pytz.timezone('Europe/Bucharest')
    now = datetime.now(tz_ro)
    
    # Formatăm ora pentru logică (HH:MM) și data pentru context
    ora_curenta = now.strftime("%H:%M")
    data_curenta = now.strftime("%d-%m-%Y")

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
                        conversation_history.append({
                            'role': msg.get('sender', 'user'),
                            'content': msg.get('message', '')
                        })
                # print(f"[DEBUG] Istoric încărcat din: {db_path}", file=sys.stderr)
            except Exception as e:
                print(f"EROARE la citirea istoricului din {db_path}: {e}", file=sys.stderr)
        else:
            print(f"[DEBUG] Fișier DB inexistent (Prima conversație?): {db_path}", file=sys.stderr)

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
    general_prompt_path = os.path.join(base_path, file_name)

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
        business_context = f"\n\n### CONTEXT ȘI REGULI COMPANIE ###\n{company_prompt_text}\n################################"
    else:
        business_context = ""

    # 3. Combinarea finală
    system_prompt_combined = f"{general_prompt}{business_context}"

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
    print(f"[DEBUG] Payload construit: {payload}", file=sys.stderr)

    return payload
