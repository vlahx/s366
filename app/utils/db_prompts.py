import sys

from app.models.sqlite_company_model import get_db
from app.utils.prompt_constants import (
    AUDIENCE_LABELS,
    PROMPT_ROLE_LABELS,
    ROLE_SORT_ORDER,
    audiences_for_user,
    normalize_audience,
    normalize_prompt_role,
)

# ----------------------------------------------------------------------
# CRUD prompturi companie (SQLite async, metadata.db per CUI)
# ----------------------------------------------------------------------


async def list_prompts(cui: str):
    db = await get_db(cui)
    if not db:
        return None

    try:
        async with db.execute(
            """
            SELECT id, name, content, prompt_role, audience, status, created_at
            FROM prompts ORDER BY created_at DESC
            """
        ) as cursor:
            return await cursor.fetchall()
    except Exception as e:
        print(f"❌ Eroare la listarea prompturilor companiei {cui}: {e}", file=sys.stderr)
        return None
    finally:
        await db.close()


async def insert_prompt(
    cui: str,
    name: str,
    content: str,
    prompt_role: str = "general",
    audience: str = "toti",
    status: str = "active",
):
    db = await get_db(cui)
    if not db:
        return {"status": "error", "message": "Conexiune DB eșuată."}

    role = normalize_prompt_role(prompt_role)
    aud = normalize_audience(audience)

    try:
        cursor = await db.execute(
            """
            INSERT INTO prompts (name, content, prompt_role, audience, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, content, role, aud, status),
        )
        await db.commit()
        return {
            "status": "success",
            "id": cursor.lastrowid,
            "message": "Prompt salvat pe NVMe.",
        }
    except Exception as e:
        print(f"❌ Eroare insert_prompt CUI {cui}: {e}", file=sys.stderr)
        return {"status": "error", "message": str(e)}
    finally:
        await db.close()


async def get_prompt_by_id(cui: str, prompt_id: int):
    db = await get_db(cui)
    if not db:
        return None

    try:
        async with db.execute(
            """
            SELECT id, name, content, prompt_role, audience, status, created_at
            FROM prompts WHERE id = ?
            """,
            (prompt_id,),
        ) as cursor:
            return await cursor.fetchone()
    except Exception as e:
        print(f"❌ Eroare la preluarea promptului {prompt_id} pentru {cui}: {e}", file=sys.stderr)
        return None
    finally:
        await db.close()


async def update_prompt(
    cui: str,
    prompt_id: int,
    name: str,
    content: str,
    prompt_role: str,
    audience: str,
    status: str = "active",
):
    db = await get_db(cui)
    if not db:
        return {"status": "error", "message": "Conexiune DB eșuată."}

    role = normalize_prompt_role(prompt_role)
    aud = normalize_audience(audience)

    try:
        await db.execute(
            """
            UPDATE prompts
            SET name = ?, content = ?, prompt_role = ?, audience = ?,
                status = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (name, content, role, aud, status, prompt_id),
        )
        await db.commit()
        return {"status": "success", "message": "Prompt actualizat cu succes."}
    except Exception as e:
        print(f"❌ Eroare update_prompt ID {prompt_id}: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        await db.close()


async def delete_prompt(cui: str, prompt_id: int):
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


def _format_prompt_block(row) -> str:
    role_key = row["prompt_role"] or "general"
    aud_key = row["audience"] or "toti"
    role_label = PROMPT_ROLE_LABELS.get(role_key, role_key)
    aud_label = AUDIENCE_LABELS.get(aud_key, aud_key)
    return (
        f"### Instrucțiuni: {row['name']} [{aud_label} | {role_label}]\n"
        f"{row['content']}\n"
        f"---"
    )


async def get_prompts_json(cui: str, user_role: str | None = None):
    """
    Prompturi active filtrate pe audiență + sortate după rol.
    """
    db = await get_db(cui)
    if not db:
        return {"company_prompt": ""}

    allowed = audiences_for_user(user_role)
    placeholders = ",".join("?" * len(allowed))
    params = (*allowed,)

    try:
        query = f"""
            SELECT name, content, prompt_role, audience
            FROM prompts
            WHERE status = 'active' AND audience IN ({placeholders})
        """
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return {"company_prompt": ""}

        sorted_rows = sorted(
            rows,
            key=lambda r: (
                ROLE_SORT_ORDER.get(r["prompt_role"] or "general", 99),
                r["name"] or "",
            ),
        )
        blocks = [_format_prompt_block(row) for row in sorted_rows]
        return {
            "status": "success",
            "company_prompt": "\n\n".join(blocks),
        }
    except Exception as e:
        print(f"❌ Eroare structurare prompte: {e}", file=sys.stderr)
        return {"company_prompt": ""}
    finally:
        await db.close()


async def count_prompts(cui: str):
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
