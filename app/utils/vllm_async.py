# app/utils/vllm_async.py
import httpx
import json
from typing import AsyncGenerator, List, Dict, Optional

class VLLMAsyncAPI:
    def __init__(self, base_url: str = "http://vllm:8000/v1"):
        """base_url va fi de obicei http://vllm:8000/v1 în docker-compose"""
        self.base_url = base_url.rstrip("/")  # elimină slash-ul final dacă există
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(600.0))  # timeout mare pt răspunsuri lungi

    async def chat_stream(
        self,
        model_name: str,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs
    ) -> AsyncGenerator[Dict, None]:
        """
        Trimite request la /v1/chat/completions cu stream=True
        Returnează chunk-uri similare cu formatul Ollama (compatibil cu codul tău existent)
        """
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 0.9,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
        }

        if tools:
            # vLLM suportă tool calling în format OpenAI
            payload["tools"] = tools
            payload["tool_choice"] = "auto"  # sau "required" dacă vrei forțat

        # Alte opțiuni comune pe care le poți trece prin kwargs
        payload.update(kwargs)

        url = f"{self.base_url}/chat/completions"

        async with self.client.stream("POST", url, json=payload) as response:
            if response.status_code >= 400:
                error_text = await response.aread()
                raise RuntimeError(f"vLLM error {response.status_code}: {error_text.decode()}")

            async for line in response.aiter_lines():
                if line.strip() == "data: [DONE]":
                    break
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:].strip())
                        # Adaptăm formatul la ce așteaptă codul tău existent
                        # vLLM trimite delta.content în choices[0].delta.content
                        if chunk.get("choices") and chunk["choices"][0].get("delta", {}).get("content"):
                            yield {
                                "message": {
                                    "role": "assistant",
                                    "content": chunk["choices"][0]["delta"]["content"]
                                }
                            }
                        # Dacă vine tool_calls
                        elif chunk.get("choices") and chunk["choices"][0].get("delta", {}).get("tool_calls"):
                            yield {
                                "message": {
                                    "role": "assistant",
                                    "tool_calls": chunk["choices"][0]["delta"]["tool_calls"]
                                }
                            }
                    except json.JSONDecodeError:
                        continue

    async def close(self):
        await self.client.aclose()