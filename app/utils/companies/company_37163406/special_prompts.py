import datetime
import sys
import mysql.connector
from app.models.mariadb import get_company_db_credentials, get_company_db_connection
from flask import session

def _connect_to_company_db(cui=None):
    """
    Functie interna pentru conectarea la baza de date a companiei.
    """
    cui = cui or session.get('company_cui')
    
    if not cui:
        print("Eroare: Nu exista CUI pentru conectarea la DB-ul companiei.", file=sys.stderr)
        return None

    credentials = get_company_db_credentials(cui)
    if not credentials:
        return None

    _, db_password, _ = credentials

    try:
        conn = get_company_db_connection(cui, db_password)
        return conn
    except mysql.connector.Error as err:
        print(f"Eroare de conexiune la DB-ul companiei {cui}: {err}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Eroare generala la conectarea la DB-ul companiei {cui}: {e}", file=sys.stderr)
        return None


def special_prompts(cui):
    """
    Extrage meniul zilei.
    """
    conn = _connect_to_company_db(cui)  # 👈 FIX IMPORTANT
    if not conn:
        return ""
    
    try:
        cursor = conn.cursor(dictionary=True)
        today = datetime.date.today().strftime("%Y-%m-%d")
        slug = f"{today}-meniu"

        query = "SELECT content FROM company_posts WHERE post_slug = %s"
        cursor.execute(query, (slug,))
        row = cursor.fetchone()

        if row and row.get('content'):
            print(f"continutul din blog: {row['content']}")
            return f"<Meniul zilei>{row['content']}</Meniul zilei>"

        return ""

    except Exception as e:
        print(f"Eroare la extragerea meniului pentru CUI {cui}: {e}", file=sys.stderr)
        return ""
    
    finally:
        if conn and conn.is_connected():
            conn.close()
