import httpx
import json

class VLLMAsyncAPI:
    def __init__(self):
        # Portul 8000 e corect pentru vLLM
        self.base_url = "http://vllm:8000/v1/chat/completions"

    async def chat_stream(self, model_name: str, messages: list, tools=None, options=None):
        # vLLM vrea doar parametri standard OpenAI
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            "temperature": float((options or {}).get("temperature", 0.0)),
            "max_tokens": int((options or {}).get("num_predict", 2048)),
            "top_p": float((options or {}).get("top_p", 0.95)),
            "tools":tools
        }

        # Dacă trimiți tools, asigură-te că vLLM a fost pornit cu --enable-auto-tool-choice
    #    if tools:
      #      payload["tools"] = tools

        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream("POST", self.base_url, json=payload) as response:
                    if response.status_code != 200:
                        # Aici vedem exact DE CE dă 400 (mesajul de eroare din body)
                        error_bytes = await response.aread()
                        error_msg = error_bytes.decode()
                        print(f"DEBUG vLLM Error: {error_msg}")
                        yield {"error": f"VLLM Error: {error_msg}", "done": True}
                        return

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue

                        content_str = line[6:].strip()
                        if content_str == "[DONE]":
                            break

                        try:
                            data = json.loads(content_str)
                            delta = data["choices"][0].get("delta", {})
                            
                            if "content" in delta and delta["content"]:
                                content = delta["content"]
                                
                                # --- LOGICA NOUĂ DE PARSARE XML ---
                                if "<tool_call>" in content or "{" in content and '"name":' in content:
                                    # Dacă detectăm un început de tool call în text, 
                                    # îl trimitem ca tool_call, nu ca text!
                                    
                                    # Notă: Aici ar trebui o logică de extragere a JSON-ului dintre tag-uri
                                    # Dar pentru test, hai să vedem dacă modelul le trimite pur text
                                    yield {"message": {"tool_calls": [{"function": {"name": "detectata_din_text", "arguments": content}}]}, "done": False}
                                else:
                                    yield {"message": {"content": content}, "done": False}

                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

            except Exception as e:
                yield {"error": f"Connection Error: {str(e)}", "done": True}

        yield {"done": True}