from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio
import json

from downloader import download_file
from uploader import upload_to_telegram, cleanup

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

class LeechRequest(BaseModel):
    url: str

# Active websocket connections
active_connections = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming WS messages if needed (e.g., start leech)
            request = json.loads(data)
            url = request.get("url")
            
            if url:
                # Start background task to not block WS
                asyncio.create_task(process_leech(url, websocket))
    except WebSocketDisconnect:
        active_connections.remove(websocket)

async def process_leech(url: str, websocket: WebSocket):
    async def send_progress(status, current, total):
        try:
            percentage = (current / total) * 100 if total > 0 else 0
            await websocket.send_json({
                "status": status,
                "current": current,
                "total": total,
                "percentage": round(percentage, 2)
            })
        except Exception:
            pass

    filepath = None
    try:
        await websocket.send_json({"status": "starting", "message": "Starting download..."})
        
        filepath = await download_file(url, send_progress)
        
        await websocket.send_json({"status": "upload_prep", "message": "Download complete. Preparing upload..."})
        
        await upload_to_telegram(filepath, send_progress)
        
        await websocket.send_json({"status": "completed", "message": "Uploaded to Telegram successfully!"})
    except Exception as e:
        await websocket.send_json({"status": "error", "message": str(e)})
    finally:
        if filepath:
            cleanup(filepath)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
