import aiosqlite
import datetime
import os
from app.utils.text_cleaner import clean_markdown_to_html

class SQLiteHandler:
    def __init__(self, db_path):
        self.db_path = db_path
        self.db = None
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    async def _connect(self):
        if self.db is None:
            self.db = await aiosqlite.connect(self.db_path)
            self.db.row_factory = aiosqlite.Row
            await self.db.execute("PRAGMA journal_mode=WAL;")
            await self.db.execute("PRAGMA foreign_keys = ON;")
            
            # Creare tabele
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    conversation_uuid TEXT PRIMARY KEY,
                    title TEXT DEFAULT 'Discuție nouă',
                    pinned INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
            """)
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL,
                    conversation_uuid TEXT NOT NULL,
                    FOREIGN KEY (conversation_uuid) REFERENCES chat_sessions (conversation_uuid) ON DELETE CASCADE
                );
            """)

            # Instalare TRIGGER pentru titlu automat
            # Se execută doar dacă titlul este cel default ('Discuție nouă')
            await self.db.execute("""
                CREATE TRIGGER IF NOT EXISTS auto_set_chat_title
                AFTER INSERT ON conversations
                BEGIN
                    UPDATE chat_sessions 
                    SET title = substr(NEW.message, 1, 30) || '...'
                    WHERE conversation_uuid = NEW.conversation_uuid 
                    AND title = 'Discuție nouă';
                END;
            """)
            
            await self.db.commit()

    async def insert_message(self, timestamp, sender, message, conversation_uuid, title=None, pinned=0):
        await self._connect()
        await self.db.execute("""
            INSERT INTO chat_sessions (conversation_uuid, title, pinned, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(conversation_uuid) DO UPDATE SET 
                updated_at = excluded.updated_at
        """, (conversation_uuid, title or 'Discuție nouă', pinned, timestamp))
        
        await self.db.execute("""
            INSERT INTO conversations (timestamp, sender, message, conversation_uuid)
            VALUES (?, ?, ?, ?)
        """, (timestamp, sender, message, conversation_uuid))
        await self.db.commit()

    async def get_all_discussions_summary(self):
        await self._connect()
        query = """
            SELECT s.conversation_uuid, s.title, s.pinned, s.updated_at,
            (SELECT message FROM conversations WHERE conversation_uuid = s.conversation_uuid 
             ORDER BY timestamp DESC LIMIT 1) AS last_message
            FROM chat_sessions s ORDER BY s.pinned DESC, s.updated_at DESC;
        """
        async with self.db.execute(query) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_conversation(self, conversation_uuid):
        await self._connect()
        async with self.db.execute("""
            SELECT c.sender, c.message, c.timestamp, s.title, s.pinned
            FROM conversations c
            JOIN chat_sessions s ON c.conversation_uuid = s.conversation_uuid
            WHERE c.conversation_uuid = ? ORDER BY c.timestamp ASC;
        """, (conversation_uuid,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_chat_meta(self, conversation_uuid, title=None, pinned=None):
        await self._connect()
        if title is not None:
            await self.db.execute("UPDATE chat_sessions SET title = ? WHERE conversation_uuid = ?", (title, conversation_uuid))
        if pinned is not None:
            await self.db.execute("UPDATE chat_sessions SET pinned = ? WHERE conversation_uuid = ?", (pinned, conversation_uuid))
        await self.db.commit()

    async def delete_conversation(self, uuid: str):
        await self._connect()
        cursor = await self.db.execute("DELETE FROM chat_sessions WHERE conversation_uuid = ?", (uuid,))
        await self.db.commit()
        return cursor.rowcount

    async def save_chat_turn(self, conversation_uuid, user_message, ai_response_raw, title=None):
        await self._connect()
        ts = datetime.datetime.now().isoformat()
        if user_message:
            await self.insert_message(ts, "user", user_message, conversation_uuid, title=title)
        if ai_response_raw and ai_response_raw.strip():
            html_response = clean_markdown_to_html(ai_response_raw)
            await self.insert_message(ts, "assistant", html_response, conversation_uuid, title=title)

    async def close(self):
        if self.db:
            await self.db.close()
            self.db = None