# run.py
import uvicorn
import os
if __name__ == '__main__':
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=5000,
        reload=True,
        workers=8,
        limit_concurrency=100,
        timeout_keep_alive=120
    )
