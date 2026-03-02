"""
Standalone Web UI server for TG Leecher Bot.

This module can be run independently to provide only the Web UI functionality,
or the web server can be started alongside the bot (see bot.py).
"""

import asyncio
import json
import os
from typing import Optional

from aiohttp import web, WSMsgType
from pyrogram import Client

from config import settings
from utils import logger, format_progress_json, cleanup_file
from downloader import Downloader, DownloadError
from uploader import Uploader
from lastperson07.aria2_client import add_download, monitor_download
from lastperson07.split_utils import split_large_file


class WebUIServer:
    """Web UI server with WebSocket support."""
    
    def __init__(self, client: Optional[Client] = None):
        self.client = client
        self.downloader = Downloader()
        self.active_downloads = {}
        self.app = web.Application()
        self.app['server'] = self
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup HTTP routes."""
        self.app.router.add_get("/", self.index_handler)
        self.app.router.add_get("/health", self.health_handler)
        self.app.router.add_get("/ws", self.websocket_handler)
        self.app.router.add_static('/static', 'static', show_index=True)
    
    async def index_handler(self, request):
        """Serve the main HTML page."""
        return web.FileResponse('static/index.html')
    
    async def health_handler(self, request):
        """Health check endpoint."""
        return web.json_response({
            "status": "ok",
            "service": "tg-leecher-web",
            "port": settings.PORT,
            "bot_connected": self.client is not None and self.client.is_connected
        })
    
    async def websocket_handler(self, request):
        """Handle WebSocket connections."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        client_ip = request.remote
        logger.info(f"WebSocket client connected from {client_ip}")
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_ws_message(msg.data, ws)
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            logger.info(f"WebSocket client {client_ip} disconnected")
        
        return ws
    
    async def _handle_ws_message(self, data: str, ws: web.WebSocketResponse):
        """Handle incoming WebSocket message."""
        try:
            message = json.loads(data)
            action = message.get("action")
            
            if action == "leech":
                url = message.get("url")
                chat_id = message.get("chat_id", settings.OWNER_ID)
                if url:
                    asyncio.create_task(self._process_leech(url, chat_id, ws))
            
            elif action == "ping":
                await ws.send_json({"action": "pong", "timestamp": message.get("timestamp")})
            
            elif action == "status":
                await ws.send_json({
                    "action": "status",
                    "bot_connected": self.client is not None and self.client.is_connected,
                    "download_dir": settings.DOWNLOAD_DIR,
                    "split_size": settings.SPLIT_SIZE,
                })
            
            else:
                await ws.send_json({"status": "error", "message": f"Unknown action: {action}"})
        
        except json.JSONDecodeError:
            await ws.send_json({"status": "error", "message": "Invalid JSON"})
        except Exception as e:
            logger.error(f"Error handling WS message: {e}")
            await ws.send_json({"status": "error", "message": str(e)})
    
    async def _process_leech(self, url: str, chat_id: int, ws: web.WebSocketResponse):
        """Process a leech request via WebSocket."""
        file_parts = []
        filepath = None
        thumb_path = None
        download_id = f"{id(ws)}_{asyncio.get_event_loop().time()}"
        
        try:
            # Check if client is available
            if not self.client or not self.client.is_connected:
                await self._send_ws_message(ws, {
                    "status": "error",
                    "message": "Bot client not connected. Please ensure bot is running."
                })
                return
            
            await self._send_ws_message(ws, {
                "status": "starting",
                "message": "Initializing download...",
                "download_id": download_id
            })
            
            self.active_downloads[download_id] = {"status": "starting", "progress": 0}
            
            # Add to aria2
            gid = await add_download(url, settings.DOWNLOAD_DIR)
            if not gid:
                await self._send_ws_message(ws, {
                    "status": "error",
                    "message": "Failed to add download. Make sure aria2c is running."
                })
                return
            
            start_time = asyncio.get_event_loop().time()
            
            # Progress callback
            async def dl_progress(action, current, total, t0, speed=0, eta_seconds=0):
                progress_data = format_progress_json(current, total, t0, action)
                progress_data.update({
                    "status": "downloading",
                    "download_id": download_id
                })
                self.active_downloads[download_id] = {
                    "status": "downloading",
                    "progress": progress_data.get("percentage", 0),
                    "current": current,
                    "total": total
                }
                await self._send_ws_message(ws, progress_data)
            
            await self._send_ws_message(ws, {
                "status": "downloading",
                "message": "Download started...",
                "download_id": download_id
            })
            
            # Monitor download
            success, result = await monitor_download(gid, dl_progress, start_time)
            
            if not success:
                await self._send_ws_message(ws, {
                    "status": "error",
                    "message": f"Download failed: {result}",
                    "download_id": download_id
                })
                return
            
            filepath = result
            if not filepath or not os.path.exists(filepath):
                await self._send_ws_message(ws, {
                    "status": "error",
                    "message": "Download completed but file not found",
                    "download_id": download_id
                })
                return
            
            filename = os.path.basename(filepath)
            file_size = os.path.getsize(filepath)
            
            await self._send_ws_message(ws, {
                "status": "processing",
                "message": f"Download complete: {filename}",
                "filename": filename,
                "file_size": file_size,
                "file_size_formatted": format_progress_json(file_size, file_size, start_time, "")["current_formatted"],
                "download_id": download_id
            })
            
            # Check if splitting is needed
            await self._send_ws_message(ws, {
                "status": "splitting",
                "message": "Checking file size for splitting...",
                "download_id": download_id
            })
            
            file_parts = await split_large_file(filepath)
            total_parts = len(file_parts)
            
            await self._send_ws_message(ws, {
                "status": "uploading",
                "message": f"Starting upload ({total_parts} part{'s' if total_parts > 1 else ''})...",
                "total_parts": total_parts,
                "download_id": download_id
            })
            
            # Initialize uploader
            uploader = Uploader(self.client)
            upload_start = asyncio.get_event_loop().time()
            
            # Upload all parts
            for idx, part in enumerate(file_parts, start=1):
                part_name = os.path.basename(part)
                part_size = os.path.getsize(part)
                
                # Build caption
                caption_lines = [
                    f"🏷 **{part_name}**",
                    f"💾 {format_progress_json(part_size, part_size, upload_start, '')['current_formatted']}"
                ]
                if total_parts > 1:
                    caption_lines.append(f"📂 Part **{idx}** of **{total_parts}**")
                caption = "\n".join(caption_lines)
                
                # Progress callback
                async def up_progress(current, total, _idx=idx, _total=total_parts):
                    # Calculate overall progress
                    completed_parts_size = sum(
                        os.path.getsize(file_parts[i]) for i in range(_idx - 1)
                    ) if _idx > 1 else 0
                    overall_current = completed_parts_size + current
                    overall_total = sum(os.path.getsize(p) for p in file_parts)
                    
                    progress_data = format_progress_json(overall_current, overall_total, upload_start, "Uploading")
                    progress_data.update({
                        "status": "uploading",
                        "part": _idx,
                        "total_parts": _total,
                        "part_progress": (current / total * 100) if total > 0 else 0,
                        "download_id": download_id
                    })
                    await self._send_ws_message(ws, progress_data)
                
                # Upload
                await uploader.upload_file(
                    chat_id=chat_id,
                    filepath=part,
                    caption=caption,
                    progress_callback=up_progress,
                )
                
                # Small delay between parts
                if idx < total_parts:
                    await asyncio.sleep(1)
            
            # Success!
            await self._send_ws_message(ws, {
                "status": "completed",
                "message": "Upload completed successfully!",
                "filename": filename,
                "parts_uploaded": total_parts,
                "download_id": download_id
            })
            
        except Exception as e:
            logger.error(f"Process leech error: {e}", exc_info=True)
            await self._send_ws_message(ws, {
                "status": "error",
                "message": str(e),
                "download_id": download_id
            })
        
        finally:
            # Cleanup
            if download_id in self.active_downloads:
                del self.active_downloads[download_id]
            
            cleanup_tasks = []
            for part in file_parts:
                if part != filepath and os.path.exists(part):
                    cleanup_tasks.append(asyncio.create_task(self._async_cleanup(part)))
            if filepath and os.path.exists(filepath):
                cleanup_tasks.append(asyncio.create_task(self._async_cleanup(filepath)))
            if thumb_path and os.path.exists(thumb_path):
                cleanup_tasks.append(asyncio.create_task(self._async_cleanup(thumb_path)))
            
            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
    
    async def _send_ws_message(self, ws: web.WebSocketResponse, data: dict):
        """Safely send a message to WebSocket."""
        try:
            if not ws.closed:
                await ws.send_json(data)
        except Exception as e:
            logger.debug(f"Failed to send WS message: {e}")
    
    async def _async_cleanup(self, filepath: str):
        """Async file cleanup."""
        try:
            cleanup_file(filepath)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
    
    async def start(self, host: str = "0.0.0.0", port: int = None):
        """Start the web server."""
        port = port or settings.PORT
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f"Web UI server started at http://{host}:{port}")
        return runner


async def main():
    """Run standalone web server."""
    # For standalone mode, we need a client
    client = Client(
        "leech_bot_web",
        api_id=settings.API_ID,
        api_hash=settings.API_HASH,
        bot_token=settings.BOT_TOKEN,
    )
    
    await client.start()
    logger.info("Bot client started for web UI")
    
    server = WebUIServer(client)
    await server.start()
    
    try:
        # Keep running
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await client.stop()


# Legacy compatibility
async def process_leech(url: str, websocket, client: Client = None):
    """Legacy function for compatibility."""
    server = WebUIServer(client)
    await server._process_leech(url, settings.OWNER_ID, websocket)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
