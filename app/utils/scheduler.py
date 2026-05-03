import asyncio
import os
from datetime import datetime
from app.utils.scraping.scraping_all import start_the_beast
from app.models.sqlite_company_model import get_company_settings, companies_data_root

async def start_global_scheduler():
    companies_path = str(companies_data_root()) 
    
    print(f"📡 [SCHEDULER] Motorul a pornit. Scanăm: {companies_path}")
    
    # Verificăm o singură dată la pornire dacă folderul există
    if not os.path.exists(companies_path):
        print(f"⚠️ [WARNING] {companies_path} nu a fost găsit! Verifică volumele Docker.")
        return

    while True:
        now_str = datetime.now().strftime("%H:%M")
       # print(now_str)
        try:
            folders = os.listdir(companies_path)
            
            for cui in folders:
                # 1. Citim setările (Asigură-te că funcția asta caută în /companies_data/{cui}/metadata.db)
                settings = await get_company_settings(cui)
                
                # 2. Curățăm și extragem datele
                enabled = settings.get("wp_scrape_enabled") == "on"
                target_url = settings.get("wp_scrape_url", "").strip()
                
                # 3. Transformăm "08:00, 18:00" în listă: ["08:00", "18:00"]
                raw_hours = settings.get("wp_scrape_hours", "")
                scheduled_list = [h.strip() for h in raw_hours.split(",") if h.strip()]
                
                # Print de debug ca să vezi în log-uri că "ticăie"
                #print(f"DEBUG [{cui}]: Ora {now_str} | Programate: {scheduled_list} | Activ: {enabled}")

                # 4. Verificăm potrivirea (Match)
                if enabled and target_url and now_str in scheduled_list:
                    print(f"🤖 [SCHEDULER] MATCH! Pornesc sincronizarea WordPress pentru {cui}...")
                    # Rulăm task-ul în background ca să nu blocăm loop-ul pentru celelalte companii
                    asyncio.create_task(start_the_beast(cui, target_url))
        
        except Exception as e:
            print(f"❌ [SCHEDULER ERROR]: {e}")

        # Așteptăm 60 de secunde până la următoarea verificare
        await asyncio.sleep(60)