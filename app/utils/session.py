import os
from fastapi import Request
from app.models.sqlite_model import fetch_one
import logging

logger = logging.getLogger(__name__)




async def sync_user_session(request: Request, user_id: int):
    """
    Sincronizează datele din SQLite Master (Users + Companies) cu Sesiunea.
    Totul rulează pe SQLite prin sqlite_model.
    """
    query = '''
        SELECT 
            u.id, u.firstname, u.lastname, u.username, u.role, u.photo_url,
            u.company_id, u.oauth_id,
            c.name as company_name, 
            c.cui as company_cui, 
            c.cif as company_cif,
            c.slug as company_slug,
            c.folder_path as company_folder,
            c.api_key as company_api_key
        FROM users u
        LEFT JOIN companies c ON u.company_id = c.company_id
        WHERE u.id = ?
    '''
    
    try:
        # Folosim fetch_one din sqlite_model-ul tău
        user_data = await fetch_one(query, (user_id,))
        
        if user_data:
            # Convertim în dict dacă fetch_one returnează Row obiect
            user_dict = dict(user_data)
            
            # Populăm sesiunea
            request.session['user_id'] = user_dict['id']
            request.session['firstname'] = user_dict['firstname'] or user_dict['username']
            request.session['lastname'] = user_dict['lastname'] or ""
            request.session['role'] = user_dict['role']
            request.session['photo_url'] = user_dict['photo_url']
            request.session['role'] = user_dict['role']
            
            # Datele firmei (vin None din LEFT JOIN dacă user_id nu are company_id)
            request.session['company_id'] = user_dict['company_id']
            request.session['company_name'] = user_dict['company_name']
            request.session['company_cui'] = user_dict['company_cui']
            request.session['company_cif'] = user_dict['company_cif']
            request.session['company_slug'] = user_dict['company_slug']
            request.session['company_folder'] = user_dict['company_folder']
            request.session['company_api_key'] = user_dict['company_api_key']
            
            print(f"[DEBUG] Session synced for user {user_id} (Company: {user_dict['company_id']})")
            return True
            
    except Exception as e:
        print(f"[ERROR] sync_user_session failed: {e}")
        
    return False


