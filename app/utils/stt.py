# utils/stt.py
import httpx
import sys

# Păstrăm URL-ul tău din rețeaua s366
WHISPER_URL = "http://whisper_s366:8000/transcribe"

async def transcribe_audio_async(audio_bytes: bytes, filename: str = "input.wav"):
    """
    Trimite bytes audio către Whisper asincron.
    audio_bytes: datele binare primite de la WebSocket
    filename: numele virtual al fișierului pentru multipart/form-data
    """
    async with httpx.AsyncClient() as client:
        try:
            # Pregătim fișierul pentru multipart upload fără să-l scriem pe disc
            files = {'audio_file': (filename, audio_bytes, 'audio/wav')}
            
            print(f"[STT INFO] Trimitere {len(audio_bytes)} bytes către Whisper...", file=sys.stderr)
            
            # Whisper poate dura, punem un timeout de 60s
            resp = await client.post(WHISPER_URL, files=files, timeout=60.0)
            resp.raise_for_status()
            
            data = resp.json()
            transcribed_text = data.get("text", "").strip()

            if not transcribed_text:
                print("[DEBUG STT] Whisper a returnat text gol.", file=sys.stderr)
                return ""

            print(f"[DEBUG STT] Text transcris: {transcribed_text}", file=sys.stderr)
            return transcribed_text

        except httpx.HTTPStatusError as e:
            print(f"[ERROR STT] Whisper a răspuns cu eroare: {e.response.status_code}", file=sys.stderr)
            return ""
        except Exception as e:
            print(f"[ERROR STT] Eroare neprevăzută la STT: {e}", file=sys.stderr)
            return ""