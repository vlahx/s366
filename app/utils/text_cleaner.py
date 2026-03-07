# /utils/text_cleaner.py
import re
import unicodedata
import markdown

# ===================================================================
# 1. FUNCTIA PENTRU CURATARE TTS (PLAIN TEXT)
# ===================================================================

def sanitize_llm_text(text: str) -> str:
    if not text:
        return ""

    # 1. ELIMINĂ TOATE TAG-URILE HTML (Inclusiv <p>, <strong>, <think>, etc.)
    # Orice începe cu < și se termină cu > zboară
    text = re.sub(r"<[^>]+>", "", text)

    # 2. Elimină markdown (caractere speciale)
    text = re.sub(r"[\*_~`#>\-+]", "", text) 

    # 3. Elimină emoji (aici e ok regex-ul tău)
    text = re.sub(
        r"[\U0001F600-\U0001F64F"
        r"\U0001F300-\U0001F5FF"
        r"\U0001F680-\U0001F6FF"
        r"\U0001F1E0-\U0001F1FF"
        r"]+", "", text, flags=re.UNICODE
    )

    # Normalizează și curăță spațiile
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text)
    
    return text.strip()


# ===================================================================
# 2. FUNCTIA PENTRU CONVERSIE HTML (AFISARE BROWSER)
# ===================================================================


def clean_markdown_to_html(markdown_text: str) -> str:
    """
    Convertește textul Markdown al LLM-ului în HTML curat, gata de afișare.
    Aplică fix-uri de pre-procesare pentru a rezolva problemele de spațiere/structură.
    """

    if not markdown_text:
        return ""

    # 1. FIX DE PRE-PROCESARE: Ajustează markdown-ul înainte de conversie
    cleaned_text = re.sub(r'([.:!])\s*(###)', r'\1\n\n\2', markdown_text)
    cleaned_text = re.sub(r'(### [^\n]+?)\s*(-)', r'\1\n\n\2', cleaned_text)
    cleaned_text = re.sub(r'---', r'\n\n---\n\n', cleaned_text)
    cleaned_text = re.sub(r"</?think>", "", cleaned_text, flags=re.IGNORECASE)

    # 2. Conversia propriu-zisă în HTML
    #md = markdown.Markdown(extensions=['extra', 'codehilite', 'nl2br'])  
    html_output = markdown.markdown(cleaned_text)

    return html_output

