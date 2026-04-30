import httpx
import re
import html
import asyncio
from bs4 import BeautifulSoup
from app.models.sqlite_company_model import get_db 
from app.utils.db_rags import chunk_document_text

# Dicționar global pentru status (vizibil în rute)
active_syncs = {}

# --- 1. UTILITAR CURĂȚARE ---
def clean_wp_content(raw_html: str) -> str:
    if not raw_html: return ""
    decoded_text = html.unescape(raw_html)
    soup = BeautifulSoup(decoded_text, "html.parser")
    for s in soup(["script", "style"]): s.decompose()
    text_only = soup.get_text(separator=' ', strip=True)
    return re.sub(r'\s+', ' ', text_only).strip()

# --- 2. DETECTOR DE PLATFORMĂ ---
async def detect_platform_deep(target_url: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True) as client:
        try:
            print(f"🔍 [Detector] Analizez: {target_url}")
            response = await client.get(target_url)
            html_content = response.text.lower()
            
            if any(x in html_content for x in ["/wp-content/", "/wp-includes/", "wp-json", 'name="generator" content="wordpress']):
                return "wordpress"
            if "drupal" in html_content: return "drupal"
            if "joomla" in html_content: return "joomla"
            return "unknown"
        except Exception as e:
            print(f"⚠️ [Detector] Eroare conexiune: {e}")
            return "error"

# --- 3. INGESTOR (Centralizat) ---
async def ingest_batch_to_rag(cui: str, batch_data: list):
    processed_count = 0
    conn = await get_db(cui)
    
    for item in batch_data:
        s_id = str(item.get('source_id'))
        # Limităm titlul la 100 ch pentru siguranța sistemului de operare (Debian)
        raw_title = item.get('title', 'Fara titlu')
        clean_title = re.sub(r'[^\w\s\.\-]', '', raw_title)
        filename_safe = (clean_title[:100] + '...') if len(clean_title) > 100 else clean_title

        text_curat = clean_wp_content(item.get('content', ''))
        if len(text_curat) < 150: continue

        text_imbogatit = f"DOCUMENT: {raw_title}\nDATA: {item.get('created_at')}\nSURSA: {item.get('url')}\nCONTINUT:\n{text_curat}"

        try:
            # Folosim INSERT OR IGNORE ca ultimă barieră de siguranță
            cursor = await conn.execute("""
                INSERT OR IGNORE INTO documents (source_id, filename, data_path, status, vectorized, type, image_url, created_at)
                VALUES (?, ?, ?, 'processing', 0, 'web', ?, ?)
            """, (s_id, filename_safe, item.get('url'), item.get('image_url'), item.get('created_at')))
            
            if cursor.rowcount > 0:
                doc_id = cursor.lastrowid
                await conn.commit()
                await chunk_document_text(cui, doc_id, text_imbogatit)
                processed_count += 1
        except Exception as e:
            print(f"❌ [Ingestor] Eroare ID {s_id}: {e}")
            
    await conn.close()
    return processed_count

# --- 4. LOGICĂ WORDPRESS (Cu golire buffer per pagină) ---

async def scrape_wordpress_logic(target_url: str, cui: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36..."}
    base_api = f"{str(target_url).strip().rstrip('/')}/wp-json/wp/v2/posts"
    
    # 1. Obținem ultima ancoră (last_id)
    conn = await get_db(cui)
    cursor = await conn.execute("SELECT MAX(CAST(source_id AS INTEGER)) FROM documents WHERE type = 'web'")
    row = await cursor.fetchone()
    last_id = int(row[0]) if row and row[0] else None
    await conn.close()

    total_new = 0
    active_syncs[str(cui)] = True

    async with httpx.AsyncClient(timeout=40.0, headers=headers) as client:
        # --- STRATEGIA A: SCANARE TOTALĂ (Prima dată) ---
        if last_id is None:
            print(f"🚀 [S366] DB Goal/Fără Web. Pornesc SCANARE TOTALĂ via Paginare.")
            page = 1
            while True:
                api_url = f"{base_api}?per_page=100&page={page}&orderby=id&order=asc&_embed"
                response = await client.get(api_url)
                if response.status_code != 200: break
                
                posts = response.json()
                if not posts: break

                batch = []
                for post in posts:
                    img = post.get('_embedded', {}).get('wp:featuredmedia', [{}])[0].get('source_url', None)
                    batch.append({
                        "source_id": int(post['id']),
                        "title": post['title']['rendered'],
                        "content": post['content']['rendered'],
                        "url": post['link'],
                        "image_url": img,
                        "created_at": post['date']
                    })
                
                if batch:
                    total_new += await ingest_batch_to_rag(cui, batch)
                page += 1

        # --- STRATEGIA B: DEEP PROBE (Incremental - 2 ori pe zi) ---
        else:
            print(f"📡 [S366] Ancora găsită: {last_id}. Pornesc DEEP PROBE (ID+1).")
            current_probe_id = last_id + 1
            misses = 0
            limit_misses = 20 # Marja de siguranță stabilită

            while misses < limit_misses:
                # Interogăm direct ID-ul următor
                probe_url = f"{base_api}/{current_probe_id}?_embed"
                
                try:
                    response = await client.get(probe_url)
                    
                    if response.status_code == 200:
                        post = response.json()
                        img = post.get('_embedded', {}).get('wp:featuredmedia', [{}])[0].get('source_url', None)
                        
                        batch = [{
                            "source_id": int(post['id']),
                            "title": post['title']['rendered'],
                            "content": post['content']['rendered'],
                            "url": post['link'],
                            "image_url": img,
                            "created_at": post['date']
                        }]
                        
                        # Ingest imediat pentru a nu pierde progresul
                        await ingest_batch_to_rag(cui, batch)
                        total_new += 1
                        print(f"✅ Articol nou găsit: ID {current_probe_id}")
                        
                        # Resetăm misses și avansăm
                        misses = 0
                        current_probe_id += 1
                        
                    elif response.status_code == 404:
                        misses += 1
                        current_probe_id += 1
                        # Debug silențios: print(f"🟡 Miss {misses}/{limit_misses} la ID {current_probe_id-1}")
                    
                    else:
                        print(f"⚠️ Eroare server ({response.status_code}) la ID {current_probe_id}")
                        break
                        
                except Exception as e:
                    print(f"❌ Eroare conexiune: {e}")
                    break

    # Finalizare
    active_syncs[str(cui)] = False
    print(f"🏆 Gata. S-au adăugat {total_new} documente noi în S366_turbo.")



# --- 5. MANAGERUL (The Beast) ---
async def start_the_beast(cui: str, target_url: str):
    # ✅ Marcăm procesul ca ACTIV în dicționarul global
    active_syncs[str(cui)] = True
    print(f"🔥 [Manager] Start The Beast pentru CUI: {cui} | URL: {target_url}")
    
    try:
        platform = await detect_platform_deep(target_url)
        
        if platform == "wordpress":
            print(f"🚀 [S366_turbo] Platformă confirmată: WordPress. Pornesc motorul...")
            await scrape_wordpress_logic(target_url, cui)
        else:
            print(f"⚠️ [S366] Platformă '{platform}' nesuportată momentan.")

    except Exception as e:
        print(f"❌ [S366] Eroare fatală Manager: {e}")
    
    finally:
        active_syncs[str(cui)] = False
        print(f"🏁 [Manager] Proces terminat pentru {cui}. Status: Inactiv.")