import aiosqlite
import os

DB_PATH = "data/db/database.db"

async def init_db():
    """Creează structura completă pentru baza de date a aplicației (S366 AI)."""
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
                api_key TEXT NOT NULL,
                reg_com TEXT,
                invoice_legal_name TEXT,
                invoice_street TEXT,
                invoice_city TEXT,
                invoice_county TEXT,
                invoice_postal_code TEXT,
                invoice_country TEXT DEFAULT 'RO',
                is_vat_payer INTEGER DEFAULT 1
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
                invoice_customer_type TEXT,
                invoice_full_name TEXT,
                invoice_street TEXT,
                invoice_city TEXT,
                invoice_county TEXT,
                invoice_postal_code TEXT,
                invoice_country TEXT DEFAULT 'RO',
                invoice_phone TEXT,
                FOREIGN KEY (company_id) REFERENCES companies (company_id) ON DELETE SET NULL
            )
        ''')

        # 2b. Migrare facturare PF/PJ (DB vechi fără coloanele de mai sus)
        async with db.execute("PRAGMA table_info(companies)") as cur:
            _co_cols = {row[1] for row in await cur.fetchall()}
        for _col, _stmt in (
            ("reg_com", "ALTER TABLE companies ADD COLUMN reg_com TEXT"),
            (
                "invoice_legal_name",
                "ALTER TABLE companies ADD COLUMN invoice_legal_name TEXT",
            ),
            ("invoice_street", "ALTER TABLE companies ADD COLUMN invoice_street TEXT"),
            ("invoice_city", "ALTER TABLE companies ADD COLUMN invoice_city TEXT"),
            ("invoice_county", "ALTER TABLE companies ADD COLUMN invoice_county TEXT"),
            (
                "invoice_postal_code",
                "ALTER TABLE companies ADD COLUMN invoice_postal_code TEXT",
            ),
            (
                "invoice_country",
                "ALTER TABLE companies ADD COLUMN invoice_country TEXT DEFAULT 'RO'",
            ),
            (
                "is_vat_payer",
                "ALTER TABLE companies ADD COLUMN is_vat_payer INTEGER DEFAULT 1",
            ),
        ):
            if _col not in _co_cols:
                await db.execute(_stmt)
                _co_cols.add(_col)

        async with db.execute("PRAGMA table_info(users)") as cur:
            _u_cols = {row[1] for row in await cur.fetchall()}
        for _col, _stmt in (
            (
                "invoice_customer_type",
                "ALTER TABLE users ADD COLUMN invoice_customer_type TEXT",
            ),
            (
                "invoice_full_name",
                "ALTER TABLE users ADD COLUMN invoice_full_name TEXT",
            ),
            ("invoice_street", "ALTER TABLE users ADD COLUMN invoice_street TEXT"),
            ("invoice_city", "ALTER TABLE users ADD COLUMN invoice_city TEXT"),
            ("invoice_county", "ALTER TABLE users ADD COLUMN invoice_county TEXT"),
            (
                "invoice_postal_code",
                "ALTER TABLE users ADD COLUMN invoice_postal_code TEXT",
            ),
            (
                "invoice_country",
                "ALTER TABLE users ADD COLUMN invoice_country TEXT DEFAULT 'RO'",
            ),
            ("invoice_phone", "ALTER TABLE users ADD COLUMN invoice_phone TEXT"),
        ):
            if _col not in _u_cols:
                await db.execute(_stmt)
                _u_cols.add(_col)

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

        # 5. Comenzi hosting (Stripe → provisioning)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS hosting_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                package_tier TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                stripe_checkout_session_id TEXT UNIQUE,
                stripe_payment_intent_id TEXT,
                stripe_customer_id TEXT,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_error TEXT,
                metadata_json TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_hosting_orders_status ON hosting_orders(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_hosting_orders_domain ON hosting_orders(domain)"
        )

        # 5b. Cote TVA (istoric — RO și altele; cota activă = ultimul rând cu effective_from <= azi)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vat_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_code TEXT NOT NULL DEFAULT 'RO',
                rate REAL NOT NULL,
                effective_from TEXT NOT NULL,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_vat_rates_country_effective "
            "ON vat_rates(country_code, effective_from)"
        )
        async with db.execute(
            "SELECT COUNT(*) FROM vat_rates WHERE UPPER(country_code) = 'RO'"
        ) as cur:
            _vat_n = await cur.fetchone()
        if not _vat_n or int(_vat_n[0] or 0) == 0:
            await db.execute(
                """
                INSERT INTO vat_rates (country_code, rate, effective_from, note)
                VALUES ('RO', 0.19, '2007-01-01', 'Seed implicit — înlocuiește cu cote reale din legislație')
                """
            )

        # 6. Plăți servicii (plată unică Stripe: mentenanță, instalări, etc.)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS service_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'eur',
                status TEXT NOT NULL DEFAULT 'pending_payment',
                stripe_checkout_session_id TEXT UNIQUE,
                stripe_payment_intent_id TEXT,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_error TEXT,
                metadata_json TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_service_payments_status ON service_payments(status)"
        )

        # 7. Idempotency webhook Stripe (comenzi hosting)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stripe_webhook_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                processed_ok INTEGER NOT NULL DEFAULT 0,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_error TEXT
            )
        """)

        # 8. Idempotency webhook Stripe (plăți servicii — endpoint separat în Dashboard)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stripe_service_webhook_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                processed_ok INTEGER NOT NULL DEFAULT 0,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_error TEXT
            )
        """)

        # 9. Blog (articole + categorii)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blog_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blog_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                category_id INTEGER,
                title TEXT NOT NULL,
                excerpt TEXT,
                content_html TEXT NOT NULL DEFAULT '',
                hero_image_url TEXT,
                og_image_width INTEGER,
                og_image_height INTEGER,
                draft INTEGER NOT NULL DEFAULT 1,
                published_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                author_firstname TEXT,
                FOREIGN KEY (category_id) REFERENCES blog_categories(id) ON DELETE SET NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_blog_posts_category ON blog_posts(category_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_blog_posts_published ON blog_posts(published_at)"
        )
        async with db.execute("PRAGMA table_info(blog_posts)") as cur:
            _blog_cols = {row[1] for row in await cur.fetchall()}
        if "author_firstname" not in _blog_cols:
            await db.execute(
                "ALTER TABLE blog_posts ADD COLUMN author_firstname TEXT"
            )

        async with db.execute("SELECT COUNT(*) FROM blog_posts") as cur:
            _bc = await cur.fetchone()
        if _bc and _bc[0] == 0:
            await db.execute(
                "INSERT OR IGNORE INTO blog_categories (slug, name, sort_order) VALUES (?, ?, ?)",
                ("noutati", "Noutăți", 0),
            )
            await db.execute(
                "INSERT OR IGNORE INTO blog_categories (slug, name, sort_order) VALUES (?, ?, ?)",
                ("ghiduri", "Ghiduri", 1),
            )
            async with db.execute(
                "SELECT id FROM blog_categories WHERE slug = ? LIMIT 1", ("noutati",)
            ) as cur:
                _row = await cur.fetchone()
            _cid = int(_row[0]) if _row else 1
            await db.execute(
                """INSERT INTO blog_posts (
                    slug, category_id, title, excerpt, content_html, draft, published_at
                ) VALUES (?, ?, ?, ?, ?, 0, datetime('now'))""",
                (
                    "bun-venit",
                    _cid,
                    "Bun venit pe blogul S366 AI",
                    "Noutăți și ghiduri despre AI, automatizare și productivitate pentru firme.",
                    "<p>Acesta este un articol inițial. Îl poți înlocui din baza de date; ulterior vom lega un editor admin.</p>",
                ),
            )

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


async def execute_insert(query, params=()):
    """INSERT și returnează lastrowid."""
    db = await get_db()
    try:
        cursor = await db.execute(query, params)
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()