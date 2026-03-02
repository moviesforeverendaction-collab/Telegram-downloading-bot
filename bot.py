import os
import time
import asyncio
import random
import subprocess
from typing import Optional

from aiohttp import web
from pyrogram import Client, filters, idle, enums
from pyrogram.types import Message

from config import settings
from utils import format_progress, format_bytes, logger, cleanup_file, get_video_info
from uploader import Uploader, safe_edit_message

from lastperson07.settings_db import (
    get_dump_channel, set_dump_channel,
    get_custom_caption, set_custom_caption,
    get_custom_thumb, set_custom_thumb
)
from lastperson07.aria2_client import add_download, monitor_download
from lastperson07.split_utils import split_large_file

# ---------------------------------------------------------------------------
# Pyrogram Bot Client
# ---------------------------------------------------------------------------
app = Client(
    "leech_bot",
    api_id=settings.API_ID,
    api_hash=settings.API_HASH,
    bot_token=settings.BOT_TOKEN,
    workers=32,
)

# Initialize uploader with the client
uploader = Uploader(app)

# ---------------------------------------------------------------------------
# Boot up Aria2 Daemon
# ---------------------------------------------------------------------------
def start_aria2_daemon():
    """Start the aria2c daemon if not already running."""
    try:
        # Check if aria2c is already running
        result = subprocess.run(
            ["pgrep", "-f", "aria2c"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            logger.info("aria2c is already running")
            return
        
        logger.info("Starting aria2c daemon...")
        subprocess.Popen([
            "aria2c",
            "--enable-rpc",
            "--rpc-listen-all=false",
            "--rpc-listen-port=6800",
            "--daemon=true",
            "--max-concurrent-downloads=5",
            "--max-connection-per-server=16",
            "--split=16",
            "--min-split-size=1M",
            "--max-overall-download-limit=0",
            "--max-download-limit=0",
        ])
        time.sleep(2)  # Give it a moment to boot
        logger.info("aria2c daemon started")
    except Exception as e:
        logger.error(f"Failed to start aria2c: {e}")


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    """Handle /start command."""
    await message.reply_text(
        "🚀 **TG Leecher Bot (Aria2 Powered)**\n\n"
        "Send me any downloadable link, magnet link, or torrent file!\n\n"
        "✅ Direct links, short links, magnets, torrents\n"
        "✂️ Auto-splits files **> 1.9 GB** natively\n"
        "📥 Super fast download / upload\n\n"
        "**Settings Commands:**\n"
        "`/setdump <channel_id>` - Set auto-upload dump channel\n"
        "`/setcaption <caption>` - Set custom caption text\n"
        "`/setthumb` (reply to image) - Set custom thumbnail image\n\n"
        "**Web UI:**\n"
        f"Access the web interface at port `{settings.PORT}`",
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@app.on_message(filters.command("help"))
async def help_handler(client: Client, message: Message):
    """Handle /help command."""
    await message.reply_text(
        "📖 **Help Guide**\n\n"
        "**Downloading:**\n"
        "• Send any direct download link\n"
        "• Send magnet links for torrents\n"
        "• Send torrent files directly\n\n"
        "**Settings:**\n"
        "• `/setdump -100XXXXXXX` - Set upload destination\n"
        "• `/setcaption My Caption` - Add custom caption\n"
        "• Reply to image with `/setthumb` - Set thumbnail\n\n"
        "**Features:**\n"
        "• Files > 1.9GB are auto-split\n"
        "• Progress tracking with speed & ETA\n"
        "• Supports video thumbnails\n"
        "• Custom captions and thumbnails",
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@app.on_message(filters.command("setdump"))
async def setdump_handler(client: Client, message: Message):
    """Handle /setdump command."""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text(
            "Usage: `/setdump -100XXXXXXX`\n\n"
            "Get your channel ID by:\n"
            "1. Adding @userinfobot to your channel\n"
            "2. Or forward a message from channel to @userinfobot",
            parse_mode=enums.ParseMode.MARKDOWN
        )
        return
    
    try:
        channel_id = int(parts[1])
        set_dump_channel(message.from_user.id, channel_id)
        await message.reply_text(f"✅ Dump channel set to: `{channel_id}`")
    except ValueError:
        await message.reply_text("❌ Invalid ID. Must be a number like `-1001234567890`")


@app.on_message(filters.command("setcaption"))
async def setcaption_handler(client: Client, message: Message):
    """Handle /setcaption command."""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        set_custom_caption(message.from_user.id, "")
        await message.reply_text("✅ Custom caption removed.")
    else:
        caption = parts[1]
        set_custom_caption(message.from_user.id, caption)
        await message.reply_text(f"✅ Custom caption set to:\n{caption}")


@app.on_message(filters.command("setthumb"))
async def setthumb_handler(client: Client, message: Message):
    """Handle /setthumb command."""
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply_text("❌ Reply to a photo with `/setthumb` to set it as thumbnail.")
        return
    
    photo = message.reply_to_message.photo
    set_custom_thumb(message.from_user.id, photo.file_id)
    await message.reply_text("✅ Custom thumbnail saved!")


@app.on_message(filters.command("status"))
async def status_handler(client: Client, message: Message):
    """Handle /status command."""
    user_id = message.from_user.id
    dump_channel = get_dump_channel(user_id)
    custom_caption = get_custom_caption(user_id)
    custom_thumb = get_custom_thumb(user_id)
    
    status_text = "📊 **Your Settings**\n\n"
    status_text += f"**Dump Channel:** `{dump_channel or 'Not set (sends to current chat)'}`\n"
    status_text += f"**Custom Caption:** {'Set ✅' if custom_caption else 'Not set'}\n"
    status_text += f"**Custom Thumbnail:** {'Set ✅' if custom_thumb else 'Not set'}\n"
    
    await message.reply_text(status_text, parse_mode=enums.ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Handle any URL / Magnet sent by the user
# ---------------------------------------------------------------------------
@app.on_message(filters.text & filters.regex(r"(https?://\S+|magnet:\?xt=urn:btih:\S+)"))
async def leech_handler(client: Client, message: Message):
    """Handle download links and magnets."""
    url = message.text.strip()
    status = await message.reply_text(
        "🔍 **Adding to Aria2...**",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    
    user_id = message.from_user.id
    target_chat_id = get_dump_channel(user_id) or message.chat.id
    custom_caption = get_custom_caption(user_id) or ""
    custom_thumb_id = get_custom_thumb(user_id)
    
    file_parts = []
    filepath = None
    thumb_path = None
    
    try:
        # 1. Download via Aria2
        gid = await add_download(url, settings.DOWNLOAD_DIR)
        if not gid:
            await safe_edit_message(status, "❌ **Error:** Could not add to aria2.\nMake sure aria2c is running.")
            return
        
        async def dl_progress(action, current, total, t0, speed=0, eta_seconds=0):
            await safe_edit_message(status, format_progress(current, total, t0, action))
        
        await safe_edit_message(status, "⬇️ **Downloading...**")
        start_time = time.time()
        
        success, result_path_or_err = await monitor_download(gid, dl_progress, start_time)
        
        if not success:
            await safe_edit_message(status, f"❌ **Aria2 Error:** `{result_path_or_err}`")
            return
        
        filepath = result_path_or_err
        if not filepath or not os.path.exists(filepath):
            await safe_edit_message(status, "❌ **Error:** Download completed but file not found on disk.")
            return
        
        filename = os.path.basename(filepath)
        size = os.path.getsize(filepath)
        
        await safe_edit_message(status, "✂️ **Checking file size for splitting...**")
        
        # 2. Split file natively if > 1.9GB
        file_parts = await split_large_file(filepath)
        total_parts = len(file_parts)
        
        # 3. Download the custom thumb if set
        if custom_thumb_id:
            try:
                thumb_path = await client.download_media(custom_thumb_id)
            except Exception as e:
                logger.warning(f"Failed to download custom thumbnail: {e}")
        
        upload_start = time.time()
        
        # 4. Upload each part
        for idx, part in enumerate(file_parts, start=1):
            part_name = os.path.basename(part)
            part_label = f"Part {idx}/{total_parts} " if total_parts > 1 else ""
            
            # Build caption
            caption_lines = [
                f"🏷 **{part_name}**",
                f"💾 {format_bytes(os.path.getsize(part))}",
            ]
            if total_parts > 1:
                caption_lines.append(f"📂 Part **{idx}** of **{total_parts}**")
            if custom_caption:
                caption_lines.append("")
                caption_lines.append(custom_caption)
            caption = "\n".join(caption_lines)
            
            # Progress callback for this part
            async def up_progress(current, total, _label=part_label, _start=upload_start):
                await safe_edit_message(
                    status,
                    format_progress(current, total, _start, f"Uploading {_label}")
                )
            
            # Upload the file
            await uploader.upload_file(
                chat_id=target_chat_id,
                filepath=part,
                caption=caption,
                thumb_path=thumb_path,
                reply_to_message_id=message.id if target_chat_id == message.chat.id and idx == 1 else None,
                progress_callback=up_progress,
                status_message=status,
            )
            
            # Brief delay between consecutive parts (anti-ban)
            if idx < total_parts:
                await asyncio.sleep(random.uniform(1.0, 2.5))
        
        await safe_edit_message(status, "✅ **All done!** 🎉")
        
    except Exception as exc:
        logger.error(f"Error in leech handler: {exc}", exc_info=True)
        await safe_edit_message(status, f"❌ **Error:** `{str(exc)[:200]}`")
    
    finally:
        # Cleanup part files
        cleanup_tasks = []
        
        for part in file_parts:
            if part != filepath and os.path.exists(part):
                cleanup_tasks.append(asyncio.create_task(async_cleanup(part)))
        
        if filepath and os.path.exists(filepath):
            cleanup_tasks.append(asyncio.create_task(async_cleanup(filepath)))
        
        if thumb_path and os.path.exists(thumb_path):
            cleanup_tasks.append(asyncio.create_task(async_cleanup(thumb_path)))
        
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)


async def async_cleanup(filepath: str):
    """Async wrapper for file cleanup."""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Cleaned up: {filepath}")
    except Exception as e:
        logger.error(f"Cleanup error for {filepath}: {e}")


# ---------------------------------------------------------------------------
# Handle torrent files
# ---------------------------------------------------------------------------
@app.on_message(filters.document)
async def torrent_handler(client: Client, message: Message):
    """Handle uploaded torrent files."""
    if not message.document or not message.document.file_name:
        return
    
    if not message.document.file_name.endswith('.torrent'):
        return
    
    # Download the torrent file
    status = await message.reply_text(
        "📥 **Downloading torrent file...**",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    
    try:
        torrent_path = await message.download()
        await safe_edit_message(status, "🔍 **Adding torrent to Aria2...**")
        
        # Read torrent file and add to aria2
        import base64
        with open(torrent_path, 'rb') as f:
            torrent_data = base64.b64encode(f.read()).decode('utf-8')
        
        # Add to aria2 using torrent data
        from lastperson07.aria2_client import aria2_rpc
        gid = await aria2_rpc("aria2.addTorrent", [torrent_data, [], {"dir": settings.DOWNLOAD_DIR}])
        
        # Clean up torrent file
        os.remove(torrent_path)
        
        if not gid:
            await safe_edit_message(status, "❌ **Error:** Could not add torrent to aria2.")
            return
        
        # Continue with same logic as URL handler
        user_id = message.from_user.id
        target_chat_id = get_dump_channel(user_id) or message.chat.id
        custom_caption = get_custom_caption(user_id) or ""
        custom_thumb_id = get_custom_thumb(user_id)
        
        file_parts = []
        filepath = None
        thumb_path = None
        
        async def dl_progress(action, current, total, t0, speed=0, eta_seconds=0):
            await safe_edit_message(status, format_progress(current, total, t0, action))
        
        await safe_edit_message(status, "⬇️ **Downloading torrent content...**")
        start_time = time.time()
        
        success, result_path_or_err = await monitor_download(gid, dl_progress, start_time)
        
        if not success:
            await safe_edit_message(status, f"❌ **Aria2 Error:** `{result_path_or_err}`")
            return
        
        filepath = result_path_or_err
        if not filepath or not os.path.exists(filepath):
            await safe_edit_message(status, "❌ **Error:** Download completed but file not found.")
            return
        
        await safe_edit_message(status, "✂️ **Checking file size...**")
        
        # Split and upload
        file_parts = await split_large_file(filepath)
        
        if custom_thumb_id:
            try:
                thumb_path = await client.download_media(custom_thumb_id)
            except Exception as e:
                logger.warning(f"Failed to download thumbnail: {e}")
        
        upload_start = time.time()
        
        for idx, part in enumerate(file_parts, start=1):
            part_name = os.path.basename(part)
            
            caption_lines = [
                f"🏷 **{part_name}**",
                f"💾 {format_bytes(os.path.getsize(part))}",
            ]
            if len(file_parts) > 1:
                caption_lines.append(f"📂 Part **{idx}** of **{len(file_parts)}**")
            if custom_caption:
                caption_lines.append("")
                caption_lines.append(custom_caption)
            caption = "\n".join(caption_lines)
            
            async def up_progress(current, total, _start=upload_start):
                await safe_edit_message(
                    status,
                    format_progress(current, total, _start, f"Uploading {idx}/{len(file_parts)}")
                )
            
            await uploader.upload_file(
                chat_id=target_chat_id,
                filepath=part,
                caption=caption,
                thumb_path=thumb_path,
                reply_to_message_id=message.id if target_chat_id == message.chat.id else None,
                progress_callback=up_progress,
                status_message=status,
            )
            
            if idx < len(file_parts):
                await asyncio.sleep(random.uniform(1.0, 2.5))
        
        await safe_edit_message(status, "✅ **Torrent download complete!** 🎉")
        
    except Exception as exc:
        logger.error(f"Error handling torrent: {exc}", exc_info=True)
        await safe_edit_message(status, f"❌ **Error:** `{str(exc)[:200]}`")
    
    finally:
        # Cleanup
        for part in file_parts:
            if part != filepath and os.path.exists(part):
                cleanup_file(part)
        if filepath:
            cleanup_file(filepath)
        if thumb_path:
            cleanup_file(thumb_path)


# ---------------------------------------------------------------------------
# Web server for health checks and Web UI
# ---------------------------------------------------------------------------
async def health_check(request):
    """Health check endpoint."""
    return web.Response(text="✅ TG Leecher is alive!")


async def websocket_handler(request):
    """Handle WebSocket connections for Web UI."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    logger.info("WebSocket client connected")
    
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                import json
                try:
                    data = json.loads(msg.data)
                    url = data.get("url")
                    
                    if url:
                        # Start download/upload in background
                        asyncio.create_task(
                            handle_websocket_leech(url, ws, request.app['client'])
                        )
                except json.JSONDecodeError:
                    await ws.send_json({"status": "error", "message": "Invalid JSON"})
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"WebSocket error: {ws.exception()}")
    except Exception as e:
        logger.error(f"WebSocket handler error: {e}")
    finally:
        logger.info("WebSocket client disconnected")
    
    return ws


async def handle_websocket_leech(url: str, ws, client: Client):
    """Handle leech request from WebSocket."""
    from utils import format_progress_json
    
    file_parts = []
    filepath = None
    
    try:
        await ws.send_json({"status": "starting", "message": "Adding to Aria2..."})
        
        gid = await add_download(url, settings.DOWNLOAD_DIR)
        if not gid:
            await ws.send_json({"status": "error", "message": "Could not add to aria2"})
            return
        
        start_time = time.time()
        
        async def dl_progress(action, current, total, t0, speed=0, eta_seconds=0):
            progress_data = format_progress_json(current, total, t0, action)
            progress_data["status"] = "downloading"
            try:
                await ws.send_json(progress_data)
            except Exception:
                pass
        
        await ws.send_json({"status": "downloading", "message": "Starting download..."})
        
        success, result_path_or_err = await monitor_download(gid, dl_progress, start_time)
        
        if not success:
            await ws.send_json({"status": "error", "message": str(result_path_or_err)})
            return
        
        filepath = result_path_or_err
        if not filepath or not os.path.exists(filepath):
            await ws.send_json({"status": "error", "message": "File not found after download"})
            return
        
        await ws.send_json({"status": "processing", "message": "Checking file size..."})
        
        # Split if needed
        file_parts = await split_large_file(filepath)
        
        # Upload to Telegram
        upload_start = time.time()
        
        for idx, part in enumerate(file_parts, start=1):
            part_label = f" ({idx}/{len(file_parts)})" if len(file_parts) > 1 else ""
            
            async def up_progress(current, total):
                progress_data = format_progress_json(current, total, upload_start, f"Uploading{part_label}")
                progress_data["status"] = "uploading"
                try:
                    await ws.send_json(progress_data)
                except Exception:
                    pass
            
            caption = f"🏷 **{os.path.basename(part)}**\n💾 {format_bytes(os.path.getsize(part))}"
            if len(file_parts) > 1:
                caption += f"\n📂 Part {idx} of {len(file_parts)}"
            
            await uploader.upload_file(
                chat_id=settings.OWNER_ID,
                filepath=part,
                caption=caption,
                progress_callback=up_progress,
            )
            
            if idx < len(file_parts):
                await asyncio.sleep(1)
        
        await ws.send_json({"status": "completed", "message": "Upload complete!"})
        
    except Exception as e:
        logger.error(f"WebSocket leech error: {e}", exc_info=True)
        try:
            await ws.send_json({"status": "error", "message": str(e)})
        except Exception:
            pass
    
    finally:
        # Cleanup
        for part in file_parts:
            if part != filepath and os.path.exists(part):
                cleanup_file(part)
        if filepath:
            cleanup_file(filepath)


async def start_web_server(client: Client):
    """Start the web server."""
    web_app = web.Application()
    web_app['client'] = client
    web_app.router.add_get("/", health_check)
    web_app.router.add_get("/ws", websocket_handler)
    
    # Serve static files for Web UI
    web_app.router.add_static('/static', 'static', show_index=True)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.PORT).start()
    logger.info(f"Web server started on port {settings.PORT}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main():
    """Main entry point."""
    start_aria2_daemon()
    
    await app.start()
    logger.info("Bot client started")
    
    await start_web_server(app)
    
    logger.info("Bot is running. Listening for messages...")
    await idle()
    
    await app.stop()
    logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
