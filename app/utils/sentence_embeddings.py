from sentence_transformers import SentenceTransformer

# Inițializăm modelul o singură dată
model = SentenceTransformer('all-MiniLM-L6-v2')  # model rapid și performant

def embed_text(text):
    """
    Returnează embedding-ul pentru un text folosind sentence-transformers.
    """
    try:
        # model.encode returnează numpy array
        emb = model.encode(text)
        return emb.tolist()  # convertim în listă de floats
    except Exception as e:
        print(f"Eroare la generarea embedding-ului: {e}")
        return []
