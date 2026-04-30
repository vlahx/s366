# utils/stt.py
import httpx
import sys

# Păstrăm URL-ul tău din rețeaua s366
WHISPER_URL = "http://whisper_s366:8000/transcribe"

async def transcribe_audio_async(audio_bytes: bytes, filename: str = "input.wav"):
    """
    Trimite bytes audio către Whisper asincron.
    Gestionează răspunsul indiferent dacă Whisper returnează un Dict sau o Listă.
    """
    async with httpx.AsyncClient() as client:
        try:
            # Pregătim fișierul pentru multipart upload
            files = {'audio_file': (filename, audio_bytes, 'audio/wav')}
            
            print(f"[STT INFO] Trimitere {len(audio_bytes)} bytes către Whisper...", file=sys.stderr)
            
            # Whisper poate dura, punem un timeout de 60s
            resp = await client.post(WHISPER_URL, files=files, timeout=60.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            # --- FIX PENTRU EROAREA 'list' object has no attribute 'get' ---
            transcribed_text = ""
            
            if isinstance(data, list):
                # Dacă e listă, de obicei textul e în primul element sau concatenăm segmentele
                # Mergem pe varianta sigură: luăm textul din primul element dacă există
                if data and isinstance(data[0], dict):
                    transcribed_text = data[0].get("text", "").strip()
                elif data and isinstance(data[0], str):
                    transcribed_text = data[0].strip()
            elif isinstance(data, dict):
                # Dacă e dicționar, extragem direct
                transcribed_text = data.get("text", "").strip()
            # --------------------------------------------------------------

            if not transcribed_text:
                print("[DEBUG STT] Whisper a returnat text gol sau format necunoscut.", file=sys.stderr)
                # Opțional: print(f"Format primit: {data}", file=sys.stderr)
                return ""

            print(f"[DEBUG STT] Text transcris: {transcribed_text}", file=sys.stderr)
            return transcribed_text

        except httpx.HTTPStatusError as e:
            print(f"[ERROR STT] Whisper a răspuns cu eroare: {e.response.status_code}", file=sys.stderr)
            return ""
        except Exception as e:
            # Acum aici nu ar mai trebui să ajungă eroarea cu 'list'
            print(f"[ERROR STT] Eroare neprevăzută la STT: {e}", file=sys.stderr)
            return ""