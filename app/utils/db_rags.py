import os
import sys
import numpy as np
import aiosqlite  
from pathlib import Path
from sentence_transformers import SentenceTransformer
from app.models.sqlite_company_model import get_db

BASE_DIR = Path(__file__).resolve().parent.parent.parent
COMPANIES_ROOT = BASE_DIR / "companies_data"

# 1. Inițializare UNICĂ (din folderul NVMe)
MODEL_LOCAL_PATH = "/app/app/models/all-MiniLM-L6-v2"
model = SentenceTransformer(MODEL_LOCAL_PATH)



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
        # Generăm vectorul ca numpy array pentru calcule rapide
        return model.encode(text)
    except Exception as e:
        print(f"❌ Eroare embedding: {e}")
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
        # Nu mai avem nevoie de data_path din SQL, o calculăm noi
        async with conn.execute("""
            SELECT id, filename, uploaded_at, status, vectorized 
            FROM documents ORDER BY uploaded_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            
            results = []
            for row in rows:
                d = dict(row)
                # Reconstruim calea la secundă pentru a vedea mărimea pe disc
                full_path = get_document_path(cui, d['filename'])
                
                if full_path.exists():
                    d['size'] = os.path.getsize(full_path)
                else:
                    d['size'] = 0
                results.append(d)
            return results
    finally:
        await conn.close()

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
    """
    Împarte textul inteligent, încercând să păstreze paragrafele întregi
    și adăugând o suprapunere (overlap) pentru context.
    """
    # 1. Curățare brută: eliminăm spațiile multiple și liniile de cuprins evidente (cele cu multe puncte)
    import re
    # Elimină linii de tipul: "1.1 Siguranță ............ 1-1"
    text = re.sub(r'\.\.\.+\s*\d+-\d+', '', text) 
    
    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        # Luăm o bucată de mărime max_length
        end = start + max_length
        if end >= text_len:
            chunks.append(text[start:].strip())
            break
            
        # Căutăm cel mai apropiat sfârșit de paragraf (\n\n) sau propoziție (. ) înapoi
        # ca să nu tăiem cuvântul sau ideea la jumătate
        chunk_end = text.rfind('\n\n', start, end)
        if chunk_end == -1 or chunk_end < start + (max_length * 0.7): # dacă nu găsim paragraf, căutăm punct
            chunk_end = text.rfind('. ', start, end)
            
        if chunk_end == -1 or chunk_end < start + (max_length * 0.7):
            # Dacă nu găsim nimic "logic", tăiem la fix
            chunk_end = end
        else:
            chunk_end += 1 # includem și punctul sau newline-ul

        chunks.append(text[start:chunk_end].strip())
        
        # Ne întoarcem puțin (overlap) ca să păstrăm contextul în următorul chunk
        start = chunk_end - overlap

    return [c for c in chunks if len(c) > 50] # Ignorăm resturile prea mici

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
        # Salvăm vectorul ca BLOB (format binar de numpy)
        await conn.execute("""
            INSERT INTO chunks (document_id, chunk_index, chunk_text, embedding)
            VALUES (?, ?, ?, ?)
        """, (document_id, chunk_index, chunk_text, embedding_vector.tobytes()))
        await conn.commit()
        return True
    finally:
        await conn.close()

# ---------------------------------------------------------
# 6. RAG: Căutare Similitudine
# ---------------------------------------------------------

async def get_rag_data(query_text, cui:str, top_k=5, threshold=0.6):
    """
    Căutare RAG cu prag de similitudine și logare în consolă.
    """
    conn = await _get_db_conn(cui)
    if not conn: 
        print(f"⚠️ [RAG] DB-ul pentru CUI {cui} lipsește.")
        return ""

    try:
        # Extragem toate chunk-urile (pentru început, pe SQLite-ul local)
        async with conn.execute("SELECT chunk_text, embedding FROM chunks") as cursor:
            rows = await cursor.fetchall()
        
        if not rows: 
            print(f"⚠️ [RAG] Nu există date vectorizate pentru CUI {cui}.")
            return ""

        query_emb = embed_text(query_text)
        results = []

        for row in rows:
            if row['embedding']:
                # Reconstruim vectorul din BLOB (float32)
                db_emb = np.frombuffer(row['embedding'], dtype=np.float32)
                
                # Cosine Similarity
                norm_q = np.linalg.norm(query_emb)
                norm_db = np.linalg.norm(db_emb)
                
                if norm_q > 0 and norm_db > 0:
                    sim = np.dot(query_emb, db_emb) / (norm_q * norm_db)
                    
                    # Verificăm pragul tău (threshold)
                    if sim >= threshold:
                        results.append((row['chunk_text'], sim))

        # Sortăm după cea mai mare similitudine
        results.sort(key=lambda x: x[1], reverse=True)

        # DEBUG PRINT (Aia de am uitat-o eu)
        if results:
            print(f"✅ [RAG] Gasite {len(results)} rezultate peste pragul {threshold}. Top score: {results[0][1]:.4f}")
        else:
            print(f"ℹ️ [RAG] Niciun rezultat n-a depășit pragul de {threshold}.")

        # Returnăm textele combinate pentru LLM
        return "\n\n".join([r[0] for r in results[:top_k]])

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