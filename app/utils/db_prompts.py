import sys
from app.models.sqlite_company_model import get_db

# ----------------------------------------------------------------------
# Functii CRUD pentru Prompturile specifice companiei (SQLite Async)
# ----------------------------------------------------------------------

async def list_prompts(cui: str):
    """
    Listeaza toate prompturile (template-uri) stocate in baza de date a companiei CUI.
    """
    db = await get_db(cui)
    if not db:
        return None
        
    try:
        async with db.execute(
            "SELECT id, name, content, type, status, created_at FROM prompts ORDER BY created_at DESC"
        ) as cursor:
            prompts = await cursor.fetchall()
            return prompts
    except Exception as e:
        print(f"❌ Eroare la listarea prompturilor companiei {cui}: {e}", file=sys.stderr)
        return None
    finally:
        await db.close()

async def insert_prompt(cui: str, name: str, content: str, p_type: str = "General", status: str = "active"):
    """
    Inserează un prompt nou pe NVMe folosind argumente individuale.
    """
    db = await get_db(cui)
    if not db:
        return {"status": "error", "message": "Conexiune DB eșuată."}

    try:
        query = """
            INSERT INTO prompts (name, content, type, status)
            VALUES (?, ?, ?, ?)
        """
        # Executăm direct cu variabilele primite
        cursor = await db.execute(query, (name, content, p_type, status))
        await db.commit()
        
        return {
            "status": "success", 
            "id": cursor.lastrowid, 
            "message": "Prompt salvat pe NVMe."
        }
    except Exception as e:
        print(f"❌ Eroare insert_prompt CUI {cui}: {e}", file=sys.stderr)
        return {"status": "error", "message": str(e)}
    finally:
        await db.close()

async def get_prompt_by_id(cui: str, prompt_id: int):
    """
    Returnează promptul ca dict pentru compania CUI.
    """
    db = await get_db(cui)
    if not db:
        return None

    try:
        async with db.execute(
            "SELECT id, name, content, type, status, created_at FROM prompts WHERE id = ?", 
            (prompt_id,)
        ) as cursor:
            prompt = await cursor.fetchone()
            return prompt
    except Exception as e:
        print(f"❌ Eroare la preluarea promptului {prompt_id} pentru {cui}: {e}", file=sys.stderr)
        return None
    finally:
        await db.close()

async def update_prompt(cui: str, prompt_id: int, name: str, content: str, p_type: str, status: str = "active"):
    """Actualizează un prompt existent pe NVMe."""
    db = await get_db(cui)
    if not db:
        return {"status": "error", "message": "Conexiune DB eșuată."}
    
    try:
        query = """
            UPDATE prompts 
            SET name = ?, content = ?, type = ?, status = ?, updated_at = datetime('now')
            WHERE id = ?
        """
        await db.execute(query, (name, content, p_type, status, prompt_id))
        await db.commit()
        return {"status": "success", "message": "Prompt actualizat cu succes."}
    except Exception as e:
        print(f"❌ Eroare update_prompt ID {prompt_id}: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await db.close()

async def delete_prompt(cui: str, prompt_id: int):
    """Sterge un prompt pentru compania CUI."""
    db = await get_db(cui)
    if not db:
        return {"status": "error", "message": "Nu s-a putut stabili conexiunea la baza de date."}
        
    try:
        cursor = await db.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        await db.commit()
        
        if cursor.rowcount == 0:
            return {"status": "error", "message": "Promptul nu a fost găsit."}
        
        return {"status": "success", "message": "Promptul a fost șters cu succes."}
    except Exception as e:
        print(f"❌ Eroare la ștergerea promptului ID {prompt_id} pentru {cui}: {e}", file=sys.stderr)
        return {"status": "error", "message": f"Eroare DB: {str(e)}"}
    finally:
        await db.close()

async def get_prompts_json(cui: str):
    db = await get_db(cui)
    if not db:
        return {"company_prompt": ""}
    
    try:
        # Luăm name, type și content pentru a structura contextul
        async with db.execute("SELECT name, type, content FROM prompts WHERE status = 'active'") as cursor:
            rows = await cursor.fetchall()
            
            if not rows:
                return {"company_prompt": ""}

            formatted_prompts = []
            for row in rows:
                # Împachetăm fiecare prompt într-o structură clară
                p_block = (
                    f"--- PROMPT COMPANIE: {row['name']} ---\n"
                    f"DEPARTAMENT: {row['type']}\n"
                    f"INSTRUCȚIUNI: {row['content']}\n"
                    f"--------------------------------------"
                )
                formatted_prompts.append(p_block)
            
            # Unim toate blocurile cu spațiu între ele
            full_context = "\n\n".join(formatted_prompts)
            
            return {
                "status": "success",
                "company_prompt": full_context
            }
    except Exception as e:
        print(f"❌ Eroare structurare prompte: {e}")
        return {"company_prompt": ""}
    finally:
        await db.close()

async def count_prompts(cui: str):
    """
    Returnează numărul total de prompte pentru o companie specifică.
    Util pentru widget-urile de statistici din Dashboard.
    """
    db = await get_db(cui)
    if not db:
        return 0
    
    try:
        async with db.execute("SELECT COUNT(*) as total FROM prompts") as cursor:
            row = await cursor.fetchone()
            return row["total"] if row else 0
    except Exception as e:
        print(f"❌ Eroare count_prompts CUI {cui}: {e}", file=sys.stderr)
        return 0
    finally:
        await db.close()        