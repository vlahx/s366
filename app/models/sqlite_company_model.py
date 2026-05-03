from pathlib import Path
import os
import aiosqlite
import sys


BASE_DIR = Path(__file__).resolve().parent.parent.parent


def companies_data_root() -> Path:
    """
    O singură rădăcină pentru `metadata.db`, `docs/` (RAG), etc.

    În Docker, setează COMPANIES_DATA_DIR la volumul montat (ex. /companies_data),
    altfel fișierele ajung sub /app/data/companies_data și nu în același loc cu mount-ul.
    """
    env = (os.getenv("COMPANIES_DATA_DIR") or "").strip()
    if env:
        return Path(env)
    return BASE_DIR / "data" / "companies_data"


# Rezolvat la import; toate modulele care importă COMPANIES_ROOT folosesc aceeași cale.
COMPANIES_ROOT: Path = companies_data_root()


def _company_root(cui: str) -> Path:
    c = str(cui).strip()
    if not c:
        raise ValueError("CUI lipsă pentru calea companiei")
    return COMPANIES_ROOT / c


def get_document_path(cui: str, filename: str = None):
    """
    Îți dă calea absolută către folderul de documente al firmei 
    sau către un fișier specific.
    """
    company_docs_dir = _company_root(cui) / "docs"
    company_docs_dir.mkdir(parents=True, exist_ok=True)

    if filename:
        return company_docs_dir / filename

    return company_docs_dir


def get_invoices_path(cui: str, filename: str | None = None) -> Path:
    """
    Facturi generate (PDF/XML etc.). Apelat la generarea facturii — creează lazy
    `{COMPANIES_ROOT}/{cui}/invoices/`.
    """
    invoices_dir = _company_root(cui) / "invoices"
    invoices_dir.mkdir(parents=True, exist_ok=True)
    if filename:
        return invoices_dir / filename
    return invoices_dir


def ensure_company_rag_layout(cui: str) -> Path:
    """
    La init companie (metadata.db): rădăcină + docs pentru RAG.
    Nu creează `invoices/` — acela e doar la emiterea facturii.
    """
    root = _company_root(cui)
    root.mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    return root


async def _ensure_documents_columns(db):
    """DB-uri vechi: CREATE IF NOT EXISTS nu adaugă coloane noi. Le alterăm aici."""
    async with db.execute('PRAGMA table_info("documents")') as cursor:
        existing = {row[1] for row in await cursor.fetchall()}
    alters = [
        ("source_id", "TEXT"),
        ("type", "TEXT NOT NULL DEFAULT 'file'"),
        ("image_url", "TEXT"),
        ("created_at", "TEXT"),
        ("uploaded_at", "TEXT"),
    ]
    for name, definition in alters:
        if name not in existing:
            await db.execute(
                f'ALTER TABLE "documents" ADD COLUMN "{name}" {definition}'
            )


# 2. Funcția de conectare
async def get_db(cui):
    """Conexiune asincronă care garantează existența tabelelor."""
    # 1. PASUL CRITIC: Rulăm inițializarea (creează folder, db, tabele, defaults)
    # Fiind "CREATE TABLE IF NOT EXISTS", nu strică nimic dacă deja există.
    await init_company_db(cui)
    
    specific_db_path = _company_root(str(cui).strip()) / "metadata.db"
    
    # Dacă după init tot nu avem path (eroare gravă de permisiuni, etc)
    if not specific_db_path.exists():
        print(f"❌ [DB] Eroare fatală: Fișierul nu a putut fi creat pentru CUI {cui}")
        return None
        
    try:
        db = await aiosqlite.connect(str(specific_db_path))
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON;")
        # Putem adăuga și un PRAGMA journal_mode=WAL; pentru viteză pe NVMe
        await db.execute("PRAGMA journal_mode = WAL;") 
        return db
    except Exception as e:
        print(f"❌ Eroare la conectare DB CUI {cui}: {e}", file=sys.stderr)
        return None


  
async def init_company_db(cui):
    """Inițializează folderul companiei, docs/ (RAG) și tabelele metadata.db."""
    root = ensure_company_rag_layout(str(cui).strip())
    db_path = root / "metadata.db"
    
    try:
        async with aiosqlite.connect(str(db_path)) as db:
            # 1. Tabelul de Prompts
            await db.execute("""
                CREATE TABLE IF NOT EXISTS "prompts" (
                    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
                    "name" TEXT NOT NULL,
                    "content" TEXT NOT NULL,
                    "type" TEXT NOT NULL CHECK("type" IN ('Intern', 'Extern', 'HR', 'SALES', 'TECH', 'General')) DEFAULT 'General',
                    "status" TEXT NOT NULL DEFAULT 'pending',
                    "created_at" TEXT DEFAULT (datetime('now')),
                    "updated_at" TEXT DEFAULT NULL
                )
            """)
            
            # 2. Tabelul de documente (RAG)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS "documents" (
                    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
                    "source_id" TEXT UNIQUE,         -- id-ul postarii extrase
                    "filename" TEXT NOT NULL,         -- Aici punem titlul scurtat (max 100 ch)
                    "data_path" TEXT NOT NULL,        -- URL-ul sursă sau calea fișierului
                    "status" TEXT NOT NULL DEFAULT 'pending',
                    "vectorized" INTEGER DEFAULT 0,
                    "type" TEXT NOT NULL DEFAULT 'file', -- 'file', 'web', 'rss', etc.
                    "image_url" TEXT,                 -- URL-ul imaginii reprezentative (de la WP)
                    "created_at" TEXT,                -- Data publicării (preluată de pe site)
                    "uploaded_at" TEXT DEFAULT (datetime('now')) -- Data la care am făcut noi sync
                )
            """)

            await _ensure_documents_columns(db)

            # 3. Tabelul Chunks (Rămâne la fel, e solid)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS "chunks" (
                    "id" INTEGER PRIMARY KEY AUTOINCREMENT, -- Adaugă AUTOINCREMENT și aici pentru siguranță
                    "document_id" INTEGER NOT NULL,
                    "chunk_index" INTEGER NOT NULL,
                    "chunk_text" TEXT NOT NULL,
                    "embedding" BLOB NOT NULL,
                    "created_at" TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY ("document_id") REFERENCES "documents" ("id") ON DELETE CASCADE           
                )
            """)

            # 4. Tabelul nou pentru Configurații RAG (REPARAT INDENTAREA AICI)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS company_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            # 5. Inserăm valorile implicite (ACTUALIZAT)
            default_settings = [
                ('rag_temperature', '0.1'),
                ('rag_top_k', '5'),
                ('rag_threshold', '0.45'),
                ('system_prompt', 'Ești un asistent tehnic util. Răspunde precis bazându-te pe contextul oferit.'),
                # Noile setări pentru automatizare
                ('wp_scrape_enabled', 'off'),      # Default dezactivat
                ('wp_scrape_url', ''),             # Gol până la configurare
                ('wp_scrape_hours', '08:00, 18:00') # Un program de bun simț default
            ]

            for key, val in default_settings:
                # Folosim INSERT OR IGNORE ca să nu suprascriem dacă firma există deja
                await db.execute("INSERT OR IGNORE INTO company_settings (key, value) VALUES (?, ?)", (key, val))

            # 6. Tabelul Posts
            await db.execute("""
                CREATE TABLE IF NOT EXISTS "company_posts" (
                    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    "title" TEXT NOT NULL,
                    "content_summary" TEXT DEFAULT NULL,
                    "content" TEXT DEFAULT NULL,
                    "created_at" TEXT NOT NULL DEFAULT (datetime('now')),
                    "post_slug" TEXT NOT NULL,
                    "is_public" BOOLEAN NOT NULL DEFAULT 1,
                    UNIQUE ("post_slug")
                )  
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scraped_content (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT,             -- ID-ul de la WP (ex: 37551)
                    platform TEXT,              -- 'wordpress'
                    content_type TEXT,          -- 'news'
                    title TEXT,                 -- Titlul curățat
                    raw_content TEXT,           -- Textul curățat (Source of Truth)
                    embedding BLOB,             -- Amprenta vectorială (mxbai-embed-large, 1024 dim)
                    url TEXT,                   -- Link original
                    price REAL DEFAULT 0.0,     
                    discount REAL DEFAULT 0.0,  
                    metadata_json TEXT,         
                    created_at TIMESTAMP,       -- Data publicării originale
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.commit()
            # Sfârșitul blocului async with - aici se închide db corect
            
        return True
    except Exception as e:
        print(f"❌ Eroare la init_db async pentru {cui}: {e}")
        return False

async def get_active_prompts(cui):
    """Exemplu de utilizare a funcției get_db."""
    db = await get_db(cui)
    if not db:
        return ""
    
    try:
        async with db.execute("SELECT name, content, type FROM prompts WHERE status = 'active'") as cursor:
            rows = await cursor.fetchall()
            
            xml_output = ""
            for row in rows:
                xml_output += f"<name>{row['name']}</name>\n"
                xml_output += f"<content>{row['content']}</content>\n"
                xml_output += f"<Type>{row['type']}</Type>\n\n"
            return xml_output.strip()
    finally:
        await db.close()

        
async def save_company_settings(cui, settings_dict):
    """
    Salvează un dicționar de setări în DB-ul firmei.
    settings_dict: {'rag_temperature': '0.3', 'rag_top_k': '7', ...}
    """
    conn = await get_db(cui) # Folosim get_db-ul tău care face și init
    if not conn:
        return False
        
    try:
        for key, value in settings_dict.items():
            await conn.execute("""
                INSERT OR REPLACE INTO company_settings (key, value)
                VALUES (?, ?)
            """, (key, str(value)))
        
        await conn.commit()
        return True
    except Exception as e:
        print(f"❌ Eroare la salvarea setărilor pentru {cui}: {e}")
        return False
    finally:
        await conn.close() 

async def get_company_settings(cui):
    """Extrage setările RAG direct și exclusiv din DB-ul firmei."""
    db = await get_db(cui)
    settings = {}
    
    if not db:
        print(f"🔴 [DB_ERROR] Nu s-a putut deschide DB pentru CUI: {cui}")
        return settings

    try:
        # Interogăm direct tabela de configurări
        async with db.execute("SELECT key, value FROM company_settings") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                # Folosim index (0, 1) dacă row nu e Row object, 
                # sau row['key'] dacă e configurat RowFactory
                try:
                    key = row['key']
                    val = row['value']
                except:
                    key, val = row[0], row[1]

               # print(f"  └─ Row found: {key} = {val}") # Debug pe fiecare rând
                
                if key in ["rag_temperature", "rag_threshold", "rag_repeat_penalty", "llm_temperature"]:
                    settings[key] = float(val)
                elif key in ["rag_num_ctx", "rag_top_k"]:
                    settings[key] = int(val)
                else:
                    settings[key] = val
                    
        
        return settings
    except Exception as e:
        print(f"❌ Eroare fatală citire settings CUI {cui}: {e}")
        return settings
    finally:
        await db.close()