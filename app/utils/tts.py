# utils/tts.py
import httpx
import sys
import time
import asyncio

# URL-urile rămân aceleași în rețeaua Docker s366
PIPER_TTS_URL = "http://piper:8000/speak-stream"
PIPER_HEALTH_URL = "http://piper:8000/health"

async def check_piper_health():
    """Verifică asincron dacă Piper este gata."""
    async with httpx.AsyncClient() as client:
        try:
            start_time = time.time()
            # Timeout scurt, nu vrem să ținem WebSocket-ul blocat
            resp = await client.get(PIPER_HEALTH_URL, timeout=5.0)
            resp.raise_for_status()
            
            data = resp.json()
            status = data.get('status', 'error')
            device = data.get('device', 'N/A')
            
            if status == 'ok':
                print(f"[TTS HEALTH] Piper OK ({device}). Timp: {time.time() - start_time:.2f}s", file=sys.stderr)
                return True
            return False
        except Exception as e:
            print(f"[TTS HEALTH ERROR] Piper indisponibil: {e}", file=sys.stderr)
            return False

async def generate_speech_async(text: str):
    """
    Generator asincron pentru streaming-ul audio.
    Îl vom folosi direct în WebSocket pentru a trimite chunk-uri către browser.
    """
    # 1. Verificăm asincron dacă Piper e "viu"
    if not await check_piper_health():
        print("[TTS ERROR] Piper nu este gata.", file=sys.stderr)
        return

    # 2. Streaming asincron către Piper
    # Folosim un timeout generos (90s) pentru că procesarea pe CPU poate dura
    timeout = httpx.Timeout(90.0, connect=5.0)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            print(f"[TTS INFO] Trimitere text către Piper (Async)...", file=sys.stderr)
            
            # Deschidem cererea în mod stream
            async with client.stream("POST", PIPER_TTS_URL, data={"text": text}) as resp:
                resp.raise_for_status()
                
                chunk_count = 0
                # Citim chunk-urile asincron pe măsură ce Piper le generează
                async for chunk in resp.aiter_bytes(chunk_size=1024):
                    if chunk:
                        chunk_count += 1
                        # Trimitem chunk-ul direct către cel care a apelat funcția (ex: WebSocket)
                        yield chunk
                
                print(f"[TTS DEBUG] Sinteză completă. {chunk_count} chunk-uri generate.", file=sys.stderr)
                
        except httpx.HTTPStatusError as e:
            print(f"[TTS ERROR] Piper a răspuns cu eroare: {e.response.status_code}", file=sys.stderr)
        except Exception as e:
            print(f"[TTS ERROR] Eroare neprevăzută la streaming-ul TTS: {e}", file=sys.stderr)