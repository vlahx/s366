import aiosqlite
import os
import sqlite3
import datetime
from app.utils.text_cleaner import clean_markdown_to_html

class SQLiteHandler:
    def __init__(self, db_path):
        self.db_path = db_path

    def force_init_db(self):
        """Metodă SINCRONĂ care forțează crearea tabelului și a folderului."""
        try:
            folder = os.path.dirname(self.db_path)
            if not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
            
            # Folosim sqlite3 standard, nu aiosqlite, pentru init
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL,
                    conversation_uuid TEXT NOT NULL
                );
            """)
            conn.commit()
            conn.close()
            # print(f"[DEBUG] DB Initialized Sincron: {self.db_path}")
        except Exception as e:
            print(f"[ERROR] force_init_db failed: {e}")    
        

    async def _get_conn(self):
        """Helper pentru a deschide o conexiune asincronă."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        # Activăm modul WAL pentru performanță pe NVMe
        await db.execute("PRAGMA journal_mode=WAL;")
        return db

    async def create_table(self):
        """Creează tabelul 'conversations' dacă nu există."""
        async with await self._get_conn() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL,
                    conversation_uuid TEXT NOT NULL
                );
            """)
            await db.commit()

    # În app/utils/sqlite_handler.py, modifică insert_message:

    async def insert_message(self, timestamp, sender, message, conversation_uuid):
        """Inserează un mesaj nou în tabel (Async)."""
        # Folosește direct aiosqlite.connect pentru a evita problemele de thread-uri
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO conversations (timestamp, sender, message, conversation_uuid)
                VALUES (?, ?, ?, ?)
            """, (timestamp, sender, message, conversation_uuid))
            await db.commit()
            
   

    async def get_all_discussions_summary(self):
        """Metoda pentru sidebar - Versiune simplificată pentru a evita thread error."""
        if not os.path.exists(self.db_path):
            return []

        query = """
            SELECT t1.conversation_uuid,
                (SELECT message FROM conversations t2 
                    WHERE t2.conversation_uuid = t1.conversation_uuid 
                    ORDER BY timestamp ASC LIMIT 1) AS title,
                (SELECT message FROM conversations t3 
                    WHERE t3.conversation_uuid = t1.conversation_uuid 
                    ORDER BY timestamp DESC LIMIT 1) AS last_message,
                (SELECT timestamp FROM conversations t4 
                    WHERE t4.conversation_uuid = t1.conversation_uuid 
                    ORDER BY timestamp DESC LIMIT 1) AS updated_at
            FROM conversations t1
            GROUP BY t1.conversation_uuid
            ORDER BY updated_at DESC;
        """
        try:
            # Conectare directă, fără WAL sau alte briz-briz-uri pentru citire rapidă
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(query) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            # Dacă tabelul nu există încă, returnăm listă goală în loc să crăpăm
            if "no such table" in str(e):
                return []
            raise e

    async def get_conversation(self, conversation_uuid):
        """Metoda pentru mesaje - Versiune stabilă."""
        if not os.path.exists(self.db_path):
            return []

        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT sender, message, timestamp
                    FROM conversations
                    WHERE conversation_uuid = ?
                    ORDER BY timestamp ASC;
                """, (conversation_uuid,)) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            if "no such table" in str(e):
                return []
            raise e

    
        
    async def save_chat_turn(self, conversation_uuid, user_message, ai_response_raw):
        """
        Salvează o rundă completă (User + AI) în mod asincron.
        """
        import datetime
        from app.utils.text_cleaner import clean_markdown_to_html
        
        ts = datetime.datetime.now().isoformat()
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # 1. Salvăm mesajul utilizatorului dacă există
                if user_message:
                    await db.execute("""
                        INSERT INTO conversations (timestamp, sender, message, conversation_uuid)
                        VALUES (?, ?, ?, ?)
                    """, (ts, "user", user_message, conversation_uuid))
                
                # 2. Salvăm răspunsul AI (transformat în HTML)
                if ai_response_raw and ai_response_raw.strip():
                    html_response = clean_markdown_to_html(ai_response_raw)
                    await db.execute("""
                        INSERT INTO conversations (timestamp, sender, message, conversation_uuid)
                        VALUES (?, ?, ?, ?)
                    """, (ts, "assistant", html_response, conversation_uuid))
                
                await db.commit()
                print(f"[DEBUG] Chat turn salvat asincron pentru UUID: {conversation_uuid}")
        except Exception as e:
            print(f"[HANDLER ERROR] save_chat_turn: {e}")    

    async def delete_conversation(self, uuid: str):
        """Șterge o sesiune întreagă după UUID"""
        query = "DELETE FROM conversations WHERE conversation_uuid = ?"
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (uuid,))
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            print(f"Eroare la ștergere: {e}")
            return 0        