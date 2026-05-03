import httpx
import re
import html
import asyncio
from bs4 import BeautifulSoup
from app.models.sqlite_company_model import get_db 
from app.utils.db_rags import embed_text 

def clean_wp_content(raw_html: str) -> str:
    """Curăță HTML-ul și Unicode-ul pentru a lăsa text pur."""
    if not raw_html: return ""
    decoded_text = html.unescape(raw_html)
    soup = BeautifulSoup(decoded_text, "html.parser")
    for s in soup(["script", "style"]): s.decompose()
    text_only = soup.get_text(separator=' ', strip=True)
    return re.sub(r'\s+', ' ', text_only).strip()

async def sync_wp_content(company_cui: str, target_url: str, count: int = 10):
    """
    Sincronizare WordPress cu debug: detecție → curățare → vectorizare → salvare.
    """
    print(f"🔍 [SCRAPER {company_cui}] Încep verificarea pentru: {target_url}")
    
    db = await get_db(company_cui)
    if not db:
        print(f"❌ [SCRAPER {company_cui}] EROARE: Nu pot accesa DB-ul companiei.")
        return

    try:
        # 1. Aflăm borna de la care plecăm
        last_id = 0
        async with db.execute("SELECT MAX(CAST(source_id AS INTEGER)) FROM scraped_content WHERE platform='wordpress'") as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                last_id = int(row[0])
        
        print(f"📊 [SCRAPER {company_cui}] Ultimul ID procesat în DB: {last_id}")

        # 2. Sonda către WordPress API cu "Masca" de Browser
        api_url = f"{target_url.rstrip('/')}/wp-json/wp/v2/posts"
        params = {"per_page": count, "_fields": "id,date,title,link,content"}
        
        # ADAUGĂ ACEST DICTIONAR DE HEADERS
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        
        print(f"🌐 [SCRAPER {company_cui}] Interoghez API: {api_url} cu User-Agent real...")
        
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            # ADĂUGĂM headers=headers în apelul de mai jos
            response = await client.get(api_url, params=params, headers=headers)
            response.raise_for_status()
            raw_posts = response.json()

        # 3. Filtrare: Doar postările cu ID mai mare decât ce avem în DB
        to_process = [p for p in raw_posts if int(p['id']) > last_id]
        
        if not to_process:
            print(f"✅ [SCRAPER {company_cui}] Totul este la zi. Nu sunt postări noi.")
            return

        print(f"🆕 [SCRAPER {company_cui}] Am găsit {len(to_process)} postări noi! Încep procesarea...")

        # 4. Procesare și Salvare
        new_entries_count = 0
        for post in reversed(to_process):
            post_id = post['id']
            title_clean = clean_wp_content(post['title']['rendered'])
            cleaned_content = clean_wp_content(post['content']['rendered'])
            
            print(f"🧠 [SCRAPER {company_cui}] Vectorizez postarea #{post_id}: '{title_clean[:50]}...'")
            
            # --- VECTORIZARE (Aici intră GPU-ul în funcțiune) ---
            text_to_embed = f"{title_clean}. {cleaned_content}"
            vector_np = embed_text(text_to_embed) 
            vector_blob = vector_np.tobytes() if vector_np is not None else None

            # --- SALVARE ---
            await db.execute("""
                INSERT INTO scraped_content (
                    source_id, platform, content_type, title, 
                    raw_content, embedding, url, created_at
                ) VALUES (?, 'wordpress', 'news', ?, ?, ?, ?, ?)
            """, (
                str(post_id), 
                title_clean, 
                cleaned_content, 
                vector_blob, 
                post['link'], 
                post['date']
            ))
            new_entries_count += 1
            print(f"💾 [SCRAPER {company_cui}] Salvat cu succes #{post_id}")

        await db.commit()
        msg = f"🚀 [SCRAPER {company_cui}] Finalizat! {new_entries_count} postări noi adăugate."
        print(msg)
        return msg

    except httpx.HTTPStatusError as e:
        err = f"❌ [SCRAPER {company_cui}] Eroare HTTP: {e.response.status_code} pentru {target_url}"
        print(err)
        return err
    except Exception as e:
        err = f"❌ [SCRAPER {company_cui}] Eroare critică: {str(e)}"
        print(err)
        return err
    finally:
        await db.close()
        print(f"🔌 [SCRAPER {company_cui}] Conexiune DB închisă.")

# app/utils/scraping/wp_scraping.py

sync_progress = {}

async def run_manual_sync(company_cui: str, target_url: str):
    """
    Versiunea BULK: Scanează pagină cu pagină (100 postări/pag) până la capăt.
    """
    # Inițializăm progresul pentru această companie
    sync_progress[company_cui] = {"current": 0, "total": 0, "status": "running"}
    
    db = await get_db(company_cui)
    if not db:
        sync_progress[company_cui]["status"] = "error"
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    page = 1
    per_page = 100 
    total_added = 0

    try:
        # 1. Aflăm borna de la care nu mai trebuie să urcăm (ID-ul cel mai mare deja existent)
        async with db.execute("SELECT MAX(CAST(source_id AS INTEGER)) FROM scraped_content WHERE platform='wordpress'") as cursor:
            row = await cursor.fetchone()
            last_id_in_db = int(row[0]) if row and row[0] else 0

        print(f"🚀 [BULK] Pornesc de la pagina {page}. Ultimul ID în DB este: {last_id_in_db}")

        while True:
            api_url = f"{target_url.rstrip('/')}/wp-json/wp/v2/posts"
            params = {
                "per_page": per_page,
                "page": page,
                "_fields": "id,date,title,link,content",
                "orderby": "id",
                "order": "desc" # Luăm de la cele mai noi spre cele mai vechi
            }

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                print(f"🌐 [SYNC] Descarc pagina {page}...")
                response = await client.get(api_url, params=params, headers=headers)
                
                # WordPress dă 400 când ceri o pagină care nu există
                if response.status_code == 400:
                    break
                response.raise_for_status()
                posts = response.json()

            if not posts:
                break

            # Filtrăm postările: le luăm doar pe cele care au ID mai mare decât ce avem în DB
            to_process = [p for p in posts if int(p['id']) > last_id_in_db]
            
            # Dacă în pagina curentă nu avem nicio postare "nouă", înseamnă că am ajuns la istoric
            if not to_process:
                print(f"✅ Am ajuns la postări deja existente la pagina {page}. Stop.")
                break

            # Actualizăm numărul total estimat pentru bara de progres (aproximativ)
            sync_progress[company_cui]["total"] += len(to_process)

            # Procesăm batch-ul de 100 (în ordine inversă ca să păstrăm cronologia)
            for post in reversed(to_process):
                post_id = post['id']
                # Folosim funcția de curățare pe care o avem deja definită
                title_clean = clean_wp_content(post['title']['rendered'])
                content_clean = clean_wp_content(post['content']['rendered'])
                
                # --- VECTORIZARE (Aici muncește RTX-ul) ---
                vector_np = embed_text(f"{title_clean}. {content_clean}")
                vector_blob = vector_np.tobytes() if vector_np is not None else None

                await db.execute("""
                    INSERT INTO scraped_content (source_id, platform, content_type, title, raw_content, embedding, url, created_at)
                    VALUES (?, 'wordpress', 'news', ?, ?, ?, ?, ?)
                """, (str(post_id), title_clean, content_clean, vector_blob, post['link'], post['date']))
                
                # Incrementăm progresul vizibil în Dashboard
                total_added += 1
                sync_progress[company_cui]["current"] = total_added

            # Salvăm progresul pe disc după fiecare pagină de 100
            await db.commit()
            print(f"💾 Pagina {page} procesată. Total adăugat: {total_added}")
            
            page += 1
            # O mică pauză să nu „ardem” API-ul WordPress sau să blocăm total Event Loop-ul
            await asyncio.sleep(0.5)

        sync_progress[company_cui]["status"] = "completed"
        return f"Sincronizare finalizată! {total_added} postări adăugate."

    except Exception as e:
        print(f"❌ [BULK ERROR]: {e}")
        sync_progress[company_cui]["status"] = "error"
    finally:
        await db.close()      