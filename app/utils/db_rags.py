import os
import sys
import numpy as np
import torch
import aiosqlite  
from pathlib import Path
from sentence_transformers import SentenceTransformer, models
from app.models.sqlite_company_model import get_db

BASE_DIR = Path(__file__).resolve().parent.parent.parent
COMPANIES_ROOT = BASE_DIR / "data/companies_data"

# 1. Detectăm device-ul o singură dată
device = 'cuda' if torch.cuda.is_available() else 'cpu'

# Calea ta unde ai dat wget
MODEL_DIR = "/app/app/models/mxbai-embed-large"

# Încărcăm componentele "la bucată" ca să nu mai verifice numele pe internet
text_embedding_model = models.Transformer(MODEL_DIR)
pooling_model = models.Pooling(text_embedding_model.get_word_embedding_dimension())

# Asamblăm modelul
model = SentenceTransformer(modules=[text_embedding_model, pooling_model], device=device)

# Dimensiune embedding mxbai (float32 → 4 bytes / dim)
EMBEDDING_DIM = 1024
EXPECTED_EMBEDDING_BYTES = EMBEDDING_DIM * 4

print(f"✅ [S366-Turbo] Creierul de 1024 (fp16) e activ pe: {model.device}")

# 3. Verificăm oficial unde stă „creierul” modelului
print(f"DEBUG: Modelul rulează acum pe: {model.device}")


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

# ---------------------------------------------------------
# 2. Funcția de Embedding (Comasată aici)
# ---------------------------------------------------------
def embed_text(text):
    try:
        # 1. Generăm embedding-ul pe GPU
        embeddings = model.encode(
            text,
            device=model.device,
            convert_to_tensor=True,
            show_progress_bar=False,
            normalize_embeddings=True  # 👈 Adăugat pentru precizie maximă
        )
        
        # 2. Îl aducem în CPU și îl transformăm în listă Python 
        # pentru a putea fi salvat direct în baza de date .db
        return embeddings.cpu().numpy().tolist() 
        
    except Exception as e:
        print(f"❌ Eroare embedding pe {model.device}: {e}")
        return None

# ---------------------------------------------------------
# 3. Conexiune Async SQLite (Cale: companies-data/CUI/metadata.db)
# ---------------------------------------------------------

async def _get_db_conn(cui: str):
    # Folosim direct logica ta care știe de COMPANIES_ROOT / cui / metadata.db
    conn = await get_db(cui)
    if conn is None:
        # Aici e clar: ori nu e creat folderul, ori metadata.db lipsește
        print(f"❌ [RAG] Nu am putut stabili conexiunea pentru CUI: {cui}")
    return conn

# ---------------------------------------------------------
# 4. Funcțiile tale de documente (Transformate în SQLite & Async)
# ---------------------------------------------------------



async def list_docs(cui: str):
    conn = await _get_db_conn(cui)
    if not conn: return []
    try:
        async with conn.execute("""
            SELECT document_id FROM chunks
            GROUP BY document_id
            HAVING MIN(LENGTH(embedding)) != ? OR MAX(LENGTH(embedding)) != ?
        """, (EXPECTED_EMBEDDING_BYTES, EXPECTED_EMBEDDING_BYTES)) as cur:
            stale_ids = {row[0] for row in await cur.fetchall()}

        async with conn.execute("""
            SELECT id, filename, uploaded_at, status, vectorized, type
            FROM documents ORDER BY uploaded_at DESC
        """) as cursor:
            rows = await cursor.fetchall()

            results = []
            for row in rows:
                d = dict(row)
                d["created_at"] = d.get("uploaded_at")
                d["ext"] = d.get("type", "file")
                d["stale_embedding"] = d["id"] in stale_ids
                full_path = get_document_path(cui, d["filename"])

                if full_path.exists():
                    d["size"] = os.path.getsize(full_path)
                else:
                    d["size"] = 0
                results.append(d)
            return results
    finally:
        await conn.close()


async def delete_chunks_for_document(cui: str, document_id: int) -> bool:
    conn = await _get_db_conn(cui)
    if not conn:
        return False
    try:
        await conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        await conn.commit()
        return True
    except Exception as e:
        print(f"❌ Eroare delete chunks: {e}")
        return False
    finally:
        await conn.close()


async def get_document_source_text(cui: str, document_id: int) -> str | None:
    """Text sursă: fișier pe disc (PDF/DOCX/txt) sau, dacă lipsește, chunk-urile existente."""
    from app.utils.extractor import extract_text_from_file

    conn = await _get_db_conn(cui)
    if not conn:
        return None
    try:
        async with conn.execute(
            "SELECT filename FROM documents WHERE id = ?",
            (document_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        filename = row["filename"]
        file_path = get_document_path(cui, filename)
        if file_path.is_file():
            text = extract_text_from_file(str(file_path))
            if text:
                return text

        async with conn.execute(
            """SELECT chunk_text FROM chunks WHERE document_id = ?
               ORDER BY chunk_index ASC""",
            (document_id,),
        ) as cursor:
            chunk_rows = await cursor.fetchall()
        if not chunk_rows:
            return None
        return "\n\n".join(r["chunk_text"] for r in chunk_rows)
    finally:
        await conn.close()


async def revectorize_document(cui: str, document_id: int) -> tuple[bool, str]:
    """
    Șterge chunk-urile vechi și re-generează embedding-uri cu modelul curent (mxbai 1024).
    """
    text = await get_document_source_text(cui, document_id)
    if not text or len(text.strip()) < 50:
        return False, "Nu există text suficient (fișier lipsă sau chunk-uri goale)."

    conn = await _get_db_conn(cui)
    if not conn:
        return False, "Nu am putut deschide baza de date."
    try:
        async with conn.execute(
            "SELECT id FROM documents WHERE id = ?",
            (document_id,),
        ) as cursor:
            if not await cursor.fetchone():
                return False, "Documentul nu există."
        await conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        await conn.execute(
            """UPDATE documents SET vectorized = 0, status = 'uploaded'
               WHERE id = ?""",
            (document_id,),
        )
        await conn.commit()
    finally:
        await conn.close()

    n_chunks = await chunk_document_text(cui, document_id, text)
    if n_chunks == 0:
        return False, "Chunking-ul nu a produs segmente valide."
    return True, f"OK: {n_chunks} chunk-uri re-vectorizate."

async def save_uploaded_document(cui, filename, data_path):
    conn = await _get_db_conn(cui)
    if not conn: return None
    try:
        # Acum primim 3 argumente, deci INSERT-ul va merge brici
        cursor = await conn.execute("""
            INSERT INTO documents (filename, data_path, status, vectorized)
            VALUES (?, ?, 'uploaded', 0)
        """, (filename, data_path))
        await conn.commit()
        return cursor.lastrowid
    finally:
        await conn.close()

# ---------------------------------------------------------
# 5. Logică Chunking & Embedding
# ---------------------------------------------------------

def chunk_text(text, max_length=900, overlap=150):
    import re
    # Curățăm textul de mizerii de tip cuprins sau spații multiple
    text = re.sub(r'\.\.\.+\s*\d+-\d+', '', text)
    text = re.sub(r' +', ' ', text)
    
    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + max_length
        if end >= text_len:
            chunks.append(text[start:].strip())
            break
            
        # Căutăm un punct de rupere logic
        chunk_end = text.rfind('\n\n', start, end)
        if chunk_end == -1 or chunk_end < start + (max_length * 0.5):
            chunk_end = text.rfind('. ', start, end)
            
        if chunk_end == -1 or chunk_end < start + (max_length * 0.5):
            chunk_end = end
        else:
            chunk_end += 1 

        chunks.append(text[start:chunk_end].strip())
        
        # Măsură de siguranță: noul start trebuie să fie măcar cu 1 caracter peste vechiul start
        new_start = chunk_end - overlap
        start = max(new_start, start + 1) 

    return [c for c in chunks if len(c) > 50]

async def chunk_document_text(cui, document_id, text, chunk_size=900):
    chunks = chunk_text(text, max_length=chunk_size)
    
    # 1. Procesăm fiecare chunk
    for idx, chunk in enumerate(chunks):
        embedding_vector = embed_text(chunk)
        if embedding_vector is not None:
            await insert_chunk(cui, document_id, idx, chunk, embedding_vector)

    # 2. FINALIZAREA: După ce am ieșit din loop, facem UPDATE în documents
    conn = await _get_db_conn(cui)
    if conn:
        try:
            await conn.execute("""
                UPDATE documents 
                SET vectorized = 1, status = 'ready' 
                WHERE id = ?
            """, (document_id,))
            await conn.commit()
            print(f"✅ [RAG] Documentul {document_id} a fost marcat ca FINALIZAT.")
        finally:
            await conn.close()
            
    return len(chunks)

async def insert_chunk(cui, document_id, chunk_index, chunk_text, embedding_vector):
    conn = await _get_db_conn(cui)
    if not conn: return False
    try:
        # Transformăm lista/array-ul înapoi în bytes pentru stocare BLOB eficientă
        # mxbai are 1024 dimensiuni, deci BLOB-ul va avea exact 4096 bytes (float32)
        vector_blob = np.array(embedding_vector, dtype=np.float32).tobytes()
        
        await conn.execute("""
            INSERT INTO chunks (document_id, chunk_index, chunk_text, embedding)
            VALUES (?, ?, ?, ?)
        """, (document_id, chunk_index, chunk_text, vector_blob))
        await conn.commit()
        return True
    except Exception as e:
        print(f"❌ Eroare la insert chunk: {e}")
        return False
    finally:
        await conn.close()

# ---------------------------------------------------------
# 6. RAG: Căutare Similitudine
# ---------------------------------------------------------

async def get_rag_data(query_text, cui: str, top_k: int, threshold: float):
    conn = await _get_db_conn(cui)
    if not conn: return ""

    try:
        # 1. Transformăm query-ul în vector (NumPy array obligatoriu)
        query_vector = np.array(embed_text(query_text), dtype=np.float32)
        
        # 2. Extragem datele
        async with conn.execute("SELECT chunk_text, embedding FROM chunks") as cursor:
            rows = await cursor.fetchall()
        
        if not rows: return ""

        results = []
        # Pre-calculăm norma query-ului o singură dată (dacă nu e deja normalizat)
        norm_q = np.linalg.norm(query_vector)

        for row in rows:
            if row[1]: # coloana 'embedding'
                # Reconstruim rapid din BLOB
                db_emb = np.frombuffer(row[1], dtype=np.float32)
                
                # Dot product rapid cu NumPy (operație vectorizată)
                dot_product = np.dot(query_vector, db_emb)
                
                # Calculăm similitudinea cosinus
                norm_db = np.linalg.norm(db_emb)
                sim = dot_product / (norm_q * norm_db) if norm_q > 0 and norm_db > 0 else 0
                
                if sim >= threshold:
                    results.append((row[0], sim))

        # 3. Sortare și limitare
        results.sort(key=lambda x: x[1], reverse=True)
        top_results = results[:top_k]

        if top_results:
            print(f"✅ [RAG] Top score: {top_results[0][1]:.4f} (Prag: {threshold})")
            return "\n\n".join([r[0] for r in top_results])
        
        return ""

    except Exception as e:
        print(f"❌ [RAG] Eroare căutare: {e}")
        return ""
    finally:
        await conn.close()

async def delete_company_document(cui: str, doc_id: int):
    """
    Funcția de ștergere: Curățăm DB-ul și NVMe-ul sincronizat.
    """
    conn = await _get_db_conn(cui)
    if not conn:
        return False, "Nu am putut deschide baza de date."

    try:
        # 1. Identificăm fișierul înainte să pierdem referința din DB
        async with conn.execute("SELECT filename FROM documents WHERE id = ?", (doc_id,)) as cursor:
            row = await cursor.fetchone()
        
        if not row:
            return False, "Documentul nu există."

        filename = row['filename']
        # Folosim utilitarul tău de căi pe care l-am definit împreună
        file_path = get_document_path(cui, filename)

        # 2. Ștergem din DB (Trigger-ul de CASCADE va rade automat și chunk-urile)
        await conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        await conn.commit()
        print(f"🗑️ [DB] Document {doc_id} eliminat.")

        # 3. Ștergem fizic de pe NVMe (Dacă există)
        if file_path.exists():
            file_path.unlink()
            print(f"🪓 [NVMe] Fișier șters: {file_path}")

        return True, "Succes"

    except Exception as e:
        print(f"❌ [DB_RAGS ERROR] {e}")
        return False, str(e)
    finally:
        await conn.close()        