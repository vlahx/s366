# app/utils/ollama_async.py
import httpx
import json

class OllamaAsyncAPI:
    def __init__(self):
        self.base_url = "http://ollama:11434/api/chat"

    async def chat_stream(self, model_name, messages, tools=None, options=None):
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            "options": options or {}, 
            "tools": tools,
            "think": False
        }
   
        
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", self.base_url, json=payload) as response:
                async for line in response.aiter_lines():
                    if line:
                        yield json.loads(line)


  #{
            #    "temperature": 0.7, # foarte bună pentru răspunsuri deterministe și precise.
            #    "num_ctx": 32768,   # perfectă pentru conversații lungi și sarcini complexe.
                #"num_predict": 256,  #  potrivită pentru răspunsuri detaliate.
             #   "top_p": 0.9, # foarte bună pentru o mai mare diversitate a răspunsurilor.
              #  "repeat_penalty": 1.1, 
               # "frequency_penalty": 0.5, 
               # "presence_penalty": 0.3,  # Reduce probabilitatea de a folosi cuvinte care nu au fost folosite înainte (valori între 0 și 1)
               # "min_top_p": 0.2, # Setează un minim pentru top_p, care controlează câte opțiuni de răspuns sunt considerate în fiecare pas de generare (valori între 0 și 1)
               # "min_length": 50, # Setează o lungime minimă a răspunsului, pentru a evita răspunsuri prea scurte (valori în tokeni)
              #  "min_freq": 2, # Setează o frecvență minimă pentru cuvinte, pentru a evita cuvinte prea rare (valori în tokeni) 
              #  "min_p": 0.1 # Setează un minim pentru probabilitatea de generare a unui token (valori între 0 și 1)
            
           # },