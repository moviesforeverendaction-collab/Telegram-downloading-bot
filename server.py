from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio
import json
import os

from downloader import download_file
from uploader import cleanup
from config import settings

app = FastAPI(title="TG Leecher API", version="2.0")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "version": "2.0",
        "downloads_dir": settings.DOWNLOAD_DIR,
    }


class LeechRequest(BaseModel):
    url: str


# Active websocket connections with lock for thread safety
active_connections = set()
connections_lock = asyncio.Lock()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    async with connections_lock:
        active_connections.add(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming WS messages
            try:
                request = json.loads(data)
                url = request.get("url")
                
                if url:
                    # Validate URL
                    if not url.startswith(("http://", "https://")):
                        await websocket.send_json({
                            "status": "error",
                            "message": "Invalid URL. Must start with http:// or https://"
                        })
                        continue
                    
                    # Start background task to not block WS
                    asyncio.create_task(process_leech(url, websocket))
                else:
                    await websocket.send_json({
                        "status": "error",
                        "message": "No URL provided"
                    })
            except json.JSONDecodeError:
                await websocket.send_json({
                    "status": "error",
                    "message": "Invalid JSON format"
                })
                
    except WebSocketDisconnect:
        async with connections_lock:
            active_connections.discard(websocket)
    except Exception as e:
        print("WebSocket error: {}".format(e))
        async with connections_lock:
            active_connections.discard(websocket)
        try:
            await websocket.close()
        except Exception:
            pass


async def process_leech(url: str, websocket: WebSocket):
    """Process download and upload with progress tracking."""
    async def send_progress(status, current, total, extra=None):
        try:
            percentage = (current / total) * 100 if total > 0 else 0
            data = {
                "status": status,
                "current": current,
                "total": total,
                "percentage": round(min(percentage, 100), 2)
            }
            if extra:
                data.update(extra)
            await websocket.send_json(data)
        except Exception:
            pass

    filepath = None
    try:
        await send_progress("resolving", 0, 0, {"message": "Resolving URL..."})
        
        filepath = await download_file(url, send_progress)
        
        file_size = os.path.getsize(filepath)
        filename = os.path.basename(filepath)
        
        await websocket.send_json({
            "status": "download_complete",
            "message": "Download complete!",
            "filename": filename,
            "filesize": file_size,
            "filepath": filepath
        })
        
    except Exception as e:
        error_msg = str(e)
        # User-friendly error messages
        if "404" in error_msg:
            error_msg = "File not found (404). The URL may be invalid or expired."
        elif "403" in error_msg:
            error_msg = "Access denied (403). The server blocked the download."
        elif "Connect" in error_msg:
            error_msg = "Connection failed. Please check your internet and the URL."
        elif "timeout" in error_msg.lower():
            error_msg = "Download timed out. The server may be slow or unresponsive."
        elif "Certificate" in error_msg:
            error_msg = "SSL certificate error. The site may have security issues."
            
        try:
            await websocket.send_json({
                "status": "error",
                "message": error_msg
            })
        except Exception:
            pass
    finally:
        # Don't cleanup immediately - let the user access the file
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=settings.PORT, reload=True)
