# app/utils/scraping/general_scraping.py
import httpx
from app.utils.scraping.wp_scraping import get_latest_wp_posts

async def detect_and_scrape(base_url: str, count: int = 5):
    """
    Detectează platforma site-ului și alege scraper-ul potrivit.
    """
    base_url = base_url.rstrip('/')
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            # 1. Verificăm dacă e WordPress (căutăm header-ul sau ruta de API)
            wp_api_url = f"{base_url}/wp-json/wp/v2/posts"
            check_response = await client.options(wp_api_url) # 'OPTIONS' e mai rapid decât 'GET'
            
            if check_response.status_code == 200 or "wp-json" in check_response.text:
                print(f"[Detector] Site-ul {base_url} este WordPress. Pornesc WP-Scraper.")
                return await get_latest_wp_posts(base_url, count)
            
            # 2. Aici vom adăuga pe viitor: elif is_shopify / elif is_rss etc.
            
            print(f"[Detector] Platformă necunoscută pentru {base_url}.")
            return []

        except Exception as e:
            print(f"[Detector] Eroare la detectarea platformei pentru {base_url}: {e}")
            return []