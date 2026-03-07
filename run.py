# run.py
if __name__ == '__main__':
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=5000,
        reload=True,               
        workers=4,             
        limit_concurrency=12,     
        timeout_keep_alive=120
    )