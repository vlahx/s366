import fitz  # PyMuPDF
from docx import Document
import io
from PIL import Image
import pytesseract

def extract_text_from_file(file_path):
    ext = file_path.split('.')[-1].lower()
    text = ""

    try:
        if ext == 'pdf':
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text()
            doc.close()

        elif ext == 'docx':
            doc = Document(file_path)
            text = "\n".join([para.text for para in doc.paragraphs])

        elif ext in ['jpg', 'jpeg', 'png', 'bmp']:
            # Folosim Tesseract pentru poze (asigură-te că e instalat în Docker)
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image, lang='ron') # 'ron' pentru română

        elif ext == 'txt':
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
                
    except Exception as e:
        print(f"❌ Eroare la extragerea textului din {ext}: {e}")
    
    return text.strip()