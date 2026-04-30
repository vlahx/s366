# app/utils/domain_ops.py
from abc import ABC, abstractmethod
import requests

class RegistrarAdapter(ABC):
    @abstractmethod
    def check_availability(self, domain: str) -> dict: pass
    @abstractmethod
    def register(self, domain: str, contact: dict) -> dict: pass

class GandiAdapter(RegistrarAdapter):
    def __init__(self, api_key: str):
        self.headers = {"X-Api-Key": api_key}
        self.base = "https://api.gandi.net/v5"
        
    def check_availability(self, domain: str):
        res = requests.get(f"{self.base}/domain/domains/{domain}", headers=self.headers)
        return res.json()
        
    def register(self, domain: str, contact: dict):
        payload = {"domain": domain, "owner": contact, "duration": 1}
        res = requests.post(f"{self.base}/domain/domains", json=payload, headers=self.headers)
        return res.json()

class PorkbunAdapter(RegistrarAdapter):
    def __init__(self, api_key: str, secret: str):
        self.base = "https://api.porkbun.com/api/json/v3"
        self.creds = {"apikey": api_key, "secretapikey": secret}
        
    def check_availability(self, domain: str):
        res = requests.post(f"{self.base}/domain/availability/{domain}", json=self.creds)
        return res.json()
        
    def register(self, domain: str, contact: dict):
        payload = {**self.creds, "domain": domain, "years": "1", **contact}
        res = requests.post(f"{self.base}/domain/register", json=payload)
        return res.json()

def get_registrar(tld: str) -> RegistrarAdapter:
    if tld == "ro":
        return GandiAdapter(api_key="YOUR_GANDI_KEY")
    return PorkbunAdapter(api_key="YOUR_PB_KEY", secret="YOUR_PB_SECRET")