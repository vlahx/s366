# run.py
import os

import uvicorn

if __name__ == "__main__":
    # Dev: implicit reload on (.:/app + SFTP). Prod: UVICORN_RELOAD=false în .env sau compose.
    reload = os.getenv("UVICORN_RELOAD", "true").lower() in ("1", "true", "yes")
    workers = int(os.getenv("UVICORN_WORKERS", "1"))
    if reload:
        workers = 1  # obligatoriu cu reload (uvicorn)

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        reload=reload,
        workers=workers,
        limit_concurrency=100,
        timeout_keep_alive=120,
    )
