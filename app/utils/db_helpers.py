import os
import uuid

def get_db_path(user_id=None, company_id=None):
    # Prefer the persistent mount inside the container when available.
    # docker-compose mounts: /users_data -> host data/users_data
    base_dir = os.getenv("USERS_DATA_DIR") or ("/users_data" if os.path.isdir("/users_data") else "data/users_data")
    db_name = 'chat.sqlite'
    user_dir = None

    # Normalize company_id (may be None / "" / "0")
    try:
        company_id_norm = int(company_id) if company_id not in (None, "", False) else None
    except (TypeError, ValueError):
        company_id_norm = None

    # 1. Cazul: User logat DAR fără companie (standalone)
    if user_id and not company_id_norm:
        standalone_dir = os.path.join(base_dir, "standalone_users", f"user_{user_id}")
        standalone_db = os.path.join(standalone_dir, db_name)

        # Fallback: dacă userul are discuții vechi într-o companie și acum company_id lipsește din sesiune,
        # alegem automat DB-ul cel mai recent găsit sub /company_*/user_{id}/chat.sqlite.
        if not os.path.exists(standalone_db):
            company_root = base_dir
            try:
                candidates = []
                for name in os.listdir(company_root):
                    if not name.startswith("company_"):
                        continue
                    cand = os.path.join(company_root, name, f"user_{user_id}", db_name)
                    if os.path.exists(cand):
                        candidates.append(cand)
                if candidates:
                    newest = max(candidates, key=lambda p: os.path.getmtime(p))
                    user_dir = os.path.dirname(newest)
                else:
                    user_dir = standalone_dir
            except Exception:
                user_dir = standalone_dir
        else:
            user_dir = standalone_dir

    # 2. Cazul: User logat ȘI cu companie
    if user_id and company_id_norm:
        user_dir = os.path.join(base_dir, f"company_{company_id_norm}", f"user_{user_id}")

    # Dacă nu s-a încadrat în niciuna (ex: anonim), user_dir rămâne None
    if not user_dir:
        return None

    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, db_name)
