import os
import uuid

def get_db_path(user_id=None, company_id=None):
    base_dir = '.data/users_data'
    db_name = 'chat.sqlite'
    user_dir = None

    # 1. Cazul: User logat DAR fără companie
    if user_id and not company_id:
        user_dir = os.path.join(base_dir, "standalone_users", f"user_{user_id}")

    # 2. Cazul: User logat ȘI cu companie
    if user_id and company_id:
        user_dir = os.path.join(base_dir, f"company_{company_id}", f"user_{user_id}")

    # Dacă nu s-a încadrat în niciuna (ex: anonim), user_dir rămâne None
    if not user_dir:
        return None

    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, db_name)
