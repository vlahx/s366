import httpx
import json
import logging
from typing import AsyncGenerator, List, Dict, Optional, Any

class VLLMAsyncAPI:
    def __init__(self, base_url: str = "http://vllm:8000/v1"):
        self.base_url = base_url.rstrip("/")
        # Timeout None este riscant, am pus un timeout generos
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(600.0))

    async def chat_stream(
        self, 
        model_name: str, 
        messages: List[Dict[str, str]], 
        tools: Optional[List[Dict]] = None, 
        options: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> AsyncGenerator[Dict, None]:
        
        # Aici facem "maparea": vLLM nu are "options", 
        # setările din options (temperature, etc.) se pun direct în payload.
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            **kwargs 
        }
        
        # Extragem parametrii din options dacă există
        if options:
            payload.update(options)
            
        if tools:
            payload["tools"] = tools

        async with self.client.stream("POST", f"{self.base_url}/chat/completions", json=payload) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    content = line[6:].strip()
                    if content == "[DONE]":
                        break
                    try:
                        chunk = json.loads(content)
                        # Adaptăm chunk-ul vLLM (OpenAI format) să arate ca cel de Ollama
                        # ca să nu trebuiască să rescrii restul aplicației
                        if "choices" in chunk and chunk["choices"][0].get("delta", {}).get("content"):
                            yield {
                                "message": {
                                    "role": "assistant",
                                    "content": chunk["choices"][0]["delta"]["content"]
                                }
                            }
                    except json.JSONDecodeError:
                        continue