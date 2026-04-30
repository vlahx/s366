import sqlite3
from pathlib import Path
from bs4 import BeautifulSoup
from app.utils.scraping.wp_scraping import get_latest_wp_posts
# Presupunem că avem un utilitar pentru AI
# from app.utils.ai_engine import generate_summary 

COMPANIES_DATA_PATH = Path("/app/data/companies_data")

async def sync_company_news(company_cui: str, target_url: str):
    db_path = COMPANIES_DATA_PATH / company_cui / "metadata.db"
    
    # 1. Tragem ultimele 5 postări de pe site-ul țintă
    raw_posts = await get_latest_wp_posts(target_url, count=5)
    
    if not raw_posts:
        return "Nicio postare găsită sau eroare de conexiune."

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    new_entries_count = 0

    for post in raw_posts:
        post_id = post['id']
        
        # 2. Verificăm dacă postarea există deja (folosim post_id ca reper)
        cursor.execute("SELECT id FROM company_posts WHERE post_id = ?", (post_id,))
        if cursor.fetchone():
            continue # Skip dacă o avem deja

        # 3. Curățăm conținutul HTML pentru AI
        soup = BeautifulSoup(post['content']['rendered'], "html.parser")
        clean_text = soup.get_text(separator=' ', strip=True)

        # 4. Generăm Rezumatul (Aici intră RTX 3060-ul în acțiune)
        # summary = await generate_summary(clean_text)
        summary = clean_text[:300] + "..." # Placeholder temporar

        # 5. Insert în baza de date locală
        cursor.execute("""
            INSERT INTO company_posts (post_id, title, content, post_slug, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            post_id, 
            post['title']['rendered'], 
            summary, 
            f"{post['date'][:10]}-stire-{post_id}", # Slug unic
            post['date']
        ))
        new_entries_count += 1

    conn.commit()
    conn.close()
    
    return f"Sincronizare terminată. {new_entries_count} știri noi adăugate."