from pathlib import Path
import os
import aiosqlite
import sys


BASE_DIR = Path(__file__).resolve().parent.parent.parent
COMPANIES_ROOT = BASE_DIR / "data/companies_data"

def get_document_path(cui: str, filename: str = None):
    """
    Îți dă calea absolută către folderul de documente al firmei 
    sau către un fișier specific.
    """
    # Construim folderul: companies_data/{cui}/docs/
    company_docs_dir = COMPANIES_ROOT / str(cui) / "docs"
    
    # Ne asigurăm că folderul există (ca să nu crape la scriere mai târziu)
    company_docs_dir.mkdir(parents=True, exist_ok=True)
    
    if filename:
        return company_docs_dir / filename
    
    return company_docs_dir



# 2. Funcția de conectare
async def get_db(cui):
    """Conexiune asincronă care garantează existența tabelelor."""
    # 1. PASUL CRITIC: Rulăm inițializarea (creează folder, db, tabele, defaults)
    # Fiind "CREATE TABLE IF NOT EXISTS", nu strică nimic dacă deja există.
    await init_company_db(cui)
    
    specific_db_path = COMPANIES_ROOT / str(cui) / "metadata.db"
    
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
    """Inițializează folderul și tabelele metadata."""
    company_dir = os.path.join(COMPANIES_ROOT, str(cui))
    os.makedirs(company_dir, exist_ok=True)
    
    db_path = os.path.join(company_dir, "metadata.db")
    
    try:
        async with aiosqlite.connect(db_path) as db:
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
            
            # 2. Tabelul de Documente
            await db.execute("""
                CREATE TABLE IF NOT EXISTS "documents" (
                    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
                    "filename" TEXT NOT NULL,
                    "data_path" TEXT NOT NULL,
                    "uploaded_at" TEXT DEFAULT (datetime('now')),
                    "status" TEXT NOT NULL DEFAULT 'pending',
                    "vectorized" INTEGER DEFAULT 0
                )
            """)
            
            # 3. Tabelul Chunks
            await db.execute("""
                CREATE TABLE IF NOT EXISTS "chunks" (
                    "id" INTEGER PRIMARY KEY,
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

            # 5. Inserăm valorile implicite (TOT ÎN INTERIORUL BLOCULUI)
            default_settings = [
                ('rag_temperature', '0.1'),
                ('rag_top_k', '5'),
                ('rag_threshold', '0.45'),
                ('system_prompt', 'Ești un asistent tehnic util. Răspunde precis bazându-te pe contextul oferit.')
            ]
            
            for key, val in default_settings:
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
            
            # DEBUG: Să vedem câte rânduri a găsit în total
            print(f"📂 [DB_FETCH] Am găsit {len(rows)} rânduri în tabela company_settings pentru {cui}")
            
            for row in rows:
                # Folosim index (0, 1) dacă row nu e Row object, 
                # sau row['key'] dacă e configurat RowFactory
                try:
                    key = row['key']
                    val = row['value']
                except:
                    key, val = row[0], row[1]

                print(f"  └─ Row found: {key} = {val}") # Debug pe fiecare rând
                
                if key in ["rag_temperature", "rag_threshold"]:
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