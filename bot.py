import os
import time
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from aiohttp import web
from config import settings
from utils import download_file, format_progress_bar, format_bytes

# Initialize Pyrogram client
app = Client(
    "leech_bot",
    api_id=settings.API_ID,
    api_hash=settings.API_HASH,
    bot_token=settings.BOT_TOKEN
)

@app.on_message(filters.command("start"))
async def start_handler(client, message: Message):
    await message.reply_text("Hello! Send me a direct download link, and I will leech it for you.")

@app.on_message(filters.text & filters.regex(r"https?://[^\s]+"))
async def leech_handler(client, message: Message):
    url = message.text
    status_msg = await message.reply_text("⏳ Processing link...")
    
    filepath = None
    try:
        async def progress(action: str, current: int, total: int, start_time: float):
            if total > 0:
                text = f"**{action}**\n{format_progress_bar(current, total)}\n{format_bytes(current)} / {format_bytes(total)}"
                try:
                    await status_msg.edit_text(text)
                except Exception:
                    pass # Ignore 'message not modified' exceptions

        # 1. Download
        await status_msg.edit_text("⏳ Downloading...")
        filepath = await download_file(url, progress)
        
        # 2. Upload
        await status_msg.edit_text("⏳ Uploading to Telegram...")
        upload_start = time.time()
        
        async def upload_progress(current, total):
            now = time.time()
            # Hacky state tracking on function to avoid global vars, Pyrogram invokes this often
            if not hasattr(upload_progress, 'last_update'):
                upload_progress.last_update = upload_start
            
            if now - upload_progress.last_update > 2.0 or current == total:
                await progress("Uploading", current, total, upload_start)
                upload_progress.last_update = now

        await app.send_document(
            chat_id=message.chat.id,
            document=filepath,
            reply_to_message_id=message.id,
            progress=upload_progress
        )
        
        await status_msg.edit_text("✅ Completed successfully!")

    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)}")
    finally:
        # 3. Cleanup
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                print(f"Cleanup error: {e}")

# --- Dummy Web Server for Render ---
async def hello(request):
    return web.Response(text="Leech Bot is running on Render!")

async def start_server():
    server = web.Application()
    server.add_routes([web.get('/', hello)])
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', settings.PORT)
    await site.start()
    print(f"Dummy Web Server running on port {settings.PORT} to satisfy Render Health Checks.")

async def main():
    await start_server()
    print("Telegram Bot Started!")
    await app.start()
    
    from pyrogram import idle
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
