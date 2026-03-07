import smtplib
from email.mime.text import MIMEText
import requests
from dotenv import load_dotenv
import os
import hashlib

# Încarcă variabilele din fișierul .env aflat în rădăcina proiectului
load_dotenv()

# Opțional: pune un print de control (șterge-l după ce confirmi)
print(f"DEBUG: Tokenul este {os.getenv('TELEGRAM_BOT_TOKEN')[:10]}...")

def send_email_notification(to_email, subject, body):
    """Trimite un mail simplu prin SMTP."""
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = os.getenv('SMTP_USER')
    msg['To'] = to_email

    try:
        with smtplib.SMTP_SSL(os.getenv('SMTP_HOST'), 465) as server:
            server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD'))
            server.sendmail(msg['From'], [to_email], msg.as_string())
        return True
    except Exception as e:
        print(f"❌ Eroare Mail: {e}")
        return False

def send_telegram_admin_alert(message, user_id):
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    admin_chat_id = os.getenv('TELEGRAM_ADMIN_CHAT_ID')
    
    # Cream un token de securitate bazat pe user_id și un SECRET din .env
    # Asta previne ghicirea URL-ului
    secret = os.getenv("APP_SECRET_KEY", "schimba-ma-pe-dell")
    secure_token = hashlib.sha256(f"{user_id}{secret}".encode()).hexdigest()[:16]
    
    base_url = "https://s366.online" # Pune IP-ul sau domeniul tau

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Aprobă", "url": f"{base_url}/admin/approve/{user_id}/{secure_token}"},
                {"text": "❌ Respinge", "url": f"{base_url}/admin/reject/{user_id}/{secure_token}"}
            ]
        ]
    }

    payload = {
        "chat_id": admin_chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": keyboard
    }
    requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload)

def send_telegram_company_approval(message, company_id):
    """
    Trimite alertă pe Telegram pentru aprobarea unei firme noi.
    Generează butoane cu link-uri securizate prin token.
    """
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    admin_chat_id = os.getenv('TELEGRAM_ADMIN_CHAT_ID')
    secret = os.getenv("APP_SECRET_KEY", "schimba-ma-pe-dell")
    
    # Token securizat specific pentru COMPANIE
    secure_token = hashlib.sha256(f"comp_{company_id}{secret}".encode()).hexdigest()[:16]
    
    # Folosim domeniul tău online
    base_url = "https://s366.online" 

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Aprobă Firma", 
                    "url": f"{base_url}/admin/approve_company/{company_id}/{secure_token}"
                },
                {
                    "text": "❌ Respinge", 
                    "url": f"{base_url}/admin/reject_company/{company_id}/{secure_token}"
                }
            ]
        ]
    }

    payload = {
        "chat_id": admin_chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": keyboard
    }
    
    try:
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload)
        return True
    except Exception as e:
        print(f"❌ Eroare trimitere Telegram Company: {e}")
        return False    