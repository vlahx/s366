import httpx
import json

class SGLangAsyncAPI:
    def __init__(self):
        
        self.base_url = "http://sglang:3000/v1/chat/completions"

    async def chat_stream(self, model_name, messages, tools=None, options=None):
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            "temperature": (options or {}).get("temperature", 0.0), 
            "max_tokens": (options or {}).get("num_predict", 2048),
        }

        if tools:
          
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            
           
            payload["tool_parser"] = "qwen2" 

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", self.base_url, json=payload) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    yield {"message": {"content": f"SGLang Error: {error_text.decode()}"}, "done": True}
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    
                    content = line[6:].strip()
                    if content == "[DONE]":
                        break

                    try:
                        data = json.loads(content)
                        delta = data["choices"][0]["delta"]

                        # Dacă modelul scrie text normal
                        if "content" in delta and delta["content"]:
                            yield {"message": {"content": delta["content"]}, "done": False}

                      
                        if "tool_calls" in delta:
                            yield {
                                "message": {"tool_calls": delta["tool_calls"]},
                                "done": False
                            }

                    except (json.JSONDecodeError, KeyError):
                        continue

        yield {"done": True}