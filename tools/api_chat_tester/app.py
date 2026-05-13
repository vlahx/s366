#!/usr/bin/env python3
"""
Tester local pentru API-ul extern S366 (/api/v1/chat/send).

Rulare pe laptop:
  cd tools/api_chat_tester
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  python app.py

Deschide http://127.0.0.1:8765 — Flask proxy-uiește către domeniul setat (evită CORS).
"""
from __future__ import annotations

import json
import os
from typing import Generator

import requests
from flask import Flask, Response, render_template, request, stream_with_context

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

DEFAULT_ENDPOINT = os.environ.get("S366_API_ENDPOINT", "https://s366.online").rstrip("/")
PORT = int(os.environ.get("PORT", "8765"))


@app.route("/")
def index():
    return render_template("index.html", default_endpoint=DEFAULT_ENDPOINT)


@app.post("/proxy/chat")
def proxy_chat():
    payload = request.get_json(silent=True) or {}
    endpoint = (payload.get("endpoint") or DEFAULT_ENDPOINT).rstrip("/")
    api_key = (payload.get("api_key") or "").strip()
    message = (payload.get("message") or "").strip()
    conv_uuid = (payload.get("conversation_uuid") or "").strip() or None

    if not api_key or not message:
        return {"ok": False, "error": "api_key și message sunt obligatorii."}, 400

    url = f"{endpoint}/api/v1/chat/send"
    body: dict = {"message": message}
    if conv_uuid:
        body["conversation_uuid"] = conv_uuid

    def generate() -> Generator[str, None, None]:
        try:
            with requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": api_key,
                    "Accept": "application/json, text/event-stream",
                },
                json=body,
                stream=True,
                timeout=(10, 300),
            ) as r:
                if r.status_code >= 400:
                    err_txt = r.text[:2000] if r.text else r.reason
                    yield json.dumps({"error": f"HTTP {r.status_code}: {err_txt}"}) + "\n"
                    return
                for raw in r.iter_lines(decode_unicode=False):
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                    if line.strip():
                        yield line + "\n"
        except requests.RequestException as e:
            yield json.dumps({"error": str(e)}) + "\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    print(f"Deschide http://127.0.0.1:{PORT} (proxy → {DEFAULT_ENDPOINT})")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
