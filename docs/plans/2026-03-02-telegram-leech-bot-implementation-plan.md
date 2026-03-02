# Render Telegram Leech Bot Implementation Plan

> **For Antigravity:** REQUIRED SUB-SKILL: Load `executing-plans` to implement this plan task-by-task.

**Goal:** Build a Telegram Bot that takes a direct link, downloads the file to its local temporary storage, and uploads it to the user's Telegram DM, designed specifically to run indefinitely on Render's free tier.

**Architecture:** Python 3 utilizing `Pyrogram` for fast Telegram interactions via MTProto and `aiohttp` for high-throughput downloading. A dummy `aiohttp.web` server binds to the Render `$PORT` to keep the deployment alive.

**Tech Stack:** Python 3, Pyrogram, tgcrypto, aiohttp.

---

### Task 1: Setup Project Structure & Dependencies

**Files:**
- Create: `requirements.txt`
- Create: `config.py`

**Step 1: Write requirements.txt**

```text
pyrogram>=2.0.100
tgcrypto>=1.2.5
aiohttp>=3.8.5
pydantic>=2.0.0
pydantic-settings>=2.0.0
```

**Step 2: Write config.py**

```python
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    API_ID: int = int(os.environ.get("API_ID", "0"))
    API_HASH: str = os.environ.get("API_HASH", "")
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
    DOWNLOAD_DIR: str = "./downloads"
    PORT: int = int(os.environ.get("PORT", "8080")) # Required for Render

settings = Settings()
os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
```

**Step 3: Commit**
```bash
git init
git add requirements.txt config.py
git commit -m "chore: setup project structure and config"
```

---

### Task 2: Implement the Downloader Module

**Files:**
- Create: `utils.py`

**Step 1: Write download and formatting logic**

```python
import aiohttp
import os
import time
from urllib.parse import urlparse
from config import settings

def format_bytes(size: int) -> str:
    power = 2**10
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{round(size, 2)}{power_labels[n]}B"

def format_progress_bar(current: int, total: int) -> str:
    percentage = current * 100 / total if total else 0
    filled = int(percentage / 10)
    bar = '▓' * filled + '░' * (10 - filled)
    return f"[{bar}] {round(percentage, 2)}%"

async def download_file(url: str, progress_callback=None):
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename:
        filename = "downloaded_file"
    
    filepath = os.path.join(settings.DOWNLOAD_DIR, filename)
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            content_length = response.headers.get('content-length')
            total_size = int(content_length) if content_length else 0
            downloaded = 0
            
            with open(filepath, 'wb') as f:
                start_time = time.time()
                last_update = start_time
                async for chunk in response.content.iter_chunked(1024 * 1024): # 1MB chunks
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    now = time.time()
                    # Only callback every 2 seconds to avoid Telegram rate limits
                    if progress_callback and (now - last_update > 2.0 or downloaded == total_size):
                        await progress_callback("Downloading", downloaded, total_size, start_time)
                        last_update = now
                        
    return filepath
```

**Step 2: Commit**

```bash
git add utils.py
git commit -m "feat: implement aiohttp downloader and formatting utils"
```

---

### Task 3: Implement the Main Bot Logic

**Files:**
- Create: `bot.py`

**Step 1: Write Pyrogram Bot handlers**

```python
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
    return web.Response(text="Leech Bot is running!")

async def start_server():
    server = web.Application()
    server.add_routes([web.get('/', hello)])
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', settings.PORT)
    await site.start()
    print(f"Dummy Web Server running on port {settings.PORT}")

async def main():
    await start_server()
    await app.start()
    print("Telegram Bot Started!")
    await pyrogram.idle()
    await app.stop()

if __name__ == "__main__":
    import pyrogram
    app.run(main())
```

**Step 2: Commit**

```bash
git add bot.py
git commit -m "feat: implement telegram bot and render web server"
```

---

### Verification Plan

You must manually verify the following to ensure the implementation is successful:
1. `pip install -r requirements.txt` succeeds.
2. Set your environment variables: `API_ID`, `API_HASH`, `BOT_TOKEN` in your terminal or `.env` file wrapper.
3. Start the bot locally: `python bot.py`
4. Send `/start` to your bot on Telegram. Ensure it replies.
5. Send a direct link (e.g. `https://files.testfile.org/PDF/10MB-TESTFILE.ORG.pdf`).
6. Verify the bot sends a downloading progress bar, then an uploading progress bar, and finally sends the document.
7. Check the local console/file system to verify the `./downloads/` folder is empty after the transfer.
