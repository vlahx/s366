import aiosqlite
import os

DB_PATH = "data/db/database.db"

async def init_db():
    """Creează structura completă pentru s366_turbo."""
    # Ne asigurăm că directorul app/db există
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    db = await aiosqlite.connect(DB_PATH)
    try:
        # 1. Tabelul Companies
        await db.execute('''
            CREATE TABLE IF NOT EXISTS companies (
                company_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                cui TEXT UNIQUE,
                cif TEXT UNIQUE,
                address TEXT,
                phone TEXT,
                email TEXT,
                status TEXT DEFAULT 'pending',
                slug TEXT NOT NULL,
                bank_account TEXT,
                folder_path TEXT,
                db_password TEXT,
                api_key TEXT NOT NULL
            )
        ''')

        # 2. Tabelul Users
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                firstname TEXT,
                lastname TEXT,
                username TEXT,
                email TEXT UNIQUE,
                password TEXT,
                role TEXT NOT NULL DEFAULT 'none',
                is_visible INTEGER DEFAULT 0,
                company_id INTEGER,
                oauth_id TEXT UNIQUE,
                photo_url TEXT,
                provider TEXT DEFAULT 'local',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fingerprint TEXT,
                FOREIGN KEY (company_id) REFERENCES companies (company_id) ON DELETE SET NULL
            )
        ''')

        # 3. Tabelul Notifications (REPARAT: am adăugat 0 la is_read și virgula)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                type TEXT DEFAULT 'info', 
                title TEXT,
                message TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies (company_id) ON DELETE CASCADE
            )
        """)

        # 4. Tabelul Visitors
        await db.execute('''
            CREATE TABLE IF NOT EXISTS visitors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                visitor_uuid TEXT UNIQUE NOT NULL,
                fingerprint TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                last_visit_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        await db.commit()
        print(f"[DATABASE] Structura verificată în {DB_PATH}")
    finally:
        await db.close()

# 1. Funcția de bază rămâne la fel, dar o folosim cu grijă
async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db

# 2. fetch_one 
async def fetch_one(query, params=()):
    # Nu mai facem "async with await"
    db = await get_db()
    try:
        async with db.execute(query, params) as cursor:
            return await cursor.fetchone()
    finally:
        await db.close()

# 3. fetch_all 
async def fetch_all(query, params=()):
    db = await get_db()
    try:
        async with db.execute(query, params) as cursor:
            return await cursor.fetchall()
    finally:
        await db.close()

# 4. execute_query 
async def execute_query(query, params=()):
    db = await get_db()
    try:
        await db.execute(query, params)
        await db.commit()
    finally:
        await db.close()