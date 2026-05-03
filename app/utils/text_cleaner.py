# /utils/text_cleaner.py
import html
import re
import unicodedata
import markdown

# ===================================================================
# 1. FUNCTIA PENTRU CURATARE TTS (PLAIN TEXT)
# ===================================================================

def assistant_bubble_to_llm_text(text: str) -> str:
    """
    Mesajele asistentului sunt salvate ca HTML (markdown → HTML în SQLite).
    Pentru următorul apel LLM trebuie text simplu: altfel modelul vede <p>…</p>
    în istoric și poate intra în bucle (tokeni repeți, tag-uri rupte).
    """
    if not text:
        return ""
    s = text.strip()
    if "<" not in s:
        return s
    t = re.sub(r"(?i)<\s*br\s*/?>", "\n", s)
    t = re.sub(r"(?i)</\s*p\s*>", "\n\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


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


md = markdown.Markdown(extensions=['extra', 'tables', 'nl2br', 'sane_lists'])

def clean_markdown_to_html(markdown_text: str) -> str:
    if not markdown_text:
        return ""

    # 1. FIX DE PRE-PROCESARE
    # Corectăm lipirea titlurilor și a listelor
    cleaned_text = re.sub(r'([.:!])\s*(###)', r'\1\n\n\2', markdown_text)
    cleaned_text = re.sub(r'(### [^\n]+?)\s*(-)', r'\1\n\n\2', cleaned_text)
    cleaned_text = re.sub(r'---', r'\n\n---\n\n', cleaned_text)
    
    # 2. Conversia rapidă
    # .convert() e mai rapid decât apelul funcției markdown.markdown() direct
    html_output = md.convert(cleaned_text)

    # Resetăm parser-ul pentru următorul apel (important la streaming!)
    md.reset() 

    return html_output

