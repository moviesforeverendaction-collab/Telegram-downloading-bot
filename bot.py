import os
import time
import asyncio
import random
import subprocess
import aiofiles

from aiohttp import web
from pyrogram import Client, filters, idle, enums
from pyrogram.types import Message

from config import settings
from utils import format_progress, format_bytes

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
)

# Anti-flood: track last edit time per message id
_last_edit_time = {}
FLOOD_COOLDOWN = 3.0

async def safe_edit(msg, text):
    """Edit a message, throttled to once per FLOOD_COOLDOWN seconds."""
    now = time.time()
    msg_id = msg.id
    if now - _last_edit_time.get(msg_id, 0) < FLOOD_COOLDOWN:
        return
    try:
        await msg.edit_text(text, parse_mode=enums.ParseMode.MARKDOWN)
        _last_edit_time[msg_id] = time.time()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Boot up Aria2 Daemon
# ---------------------------------------------------------------------------
def start_aria2_daemon():
    print("Starting aria2c daemon...")
    subprocess.Popen([
        "aria2c",
        "--enable-rpc",
        "--rpc-listen-all=false",
        "--rpc-listen-port=6800",
        "--daemon=true"
    ])
    time.sleep(2)  # Give it a moment to boot


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text(
        "🚀 **TG Leecher Bot (Aria2 Powered)**\n\n"
        "Send me any downloadable link / magnet / torrent!\n\n"
        "✅ Direct links, short links, magnets, torrents\n"
        "✂️ Auto-splits files **> 1.9 GB** natively\n"
        "📥 Super fast download / upload\n\n"
        "**Settings Commands:**\n"
        "`/setdump <channel_id>` - Set auto-upload dump channel\n"
        "`/setcaption <caption>` - Set custom caption text\n"
        "`/setthumb` (reply to image) - Set custom thumbnail image",
        parse_mode=enums.ParseMode.MARKDOWN,
    )

@app.on_message(filters.command("setdump"))
async def setdump_handler(client, message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("Usage: `/setdump -100XXXXX`")
        return
    try:
        channel_id = int(parts[1])
        set_dump_channel(message.from_user.id, channel_id)
        await message.reply_text(f"✅ Dump channel set to: `{channel_id}`")
    except ValueError:
        await message.reply_text("❌ Invalid ID.")

@app.on_message(filters.command("setcaption"))
async def setcaption_handler(client, message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        caption = ""
        set_custom_caption(message.from_user.id, caption)
        await message.reply_text("✅ Custom caption removed.")
    else:
        caption = parts[1]
        set_custom_caption(message.from_user.id, caption)
        await message.reply_text(f"✅ Custom caption set to:\n{caption}")

@app.on_message(filters.command("setthumb"))
async def setthumb_handler(client, message):
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply_text("❌ Reply to a photo with `/setthumb` to set it.")
        return
        
    photo = message.reply_to_message.photo
    set_custom_thumb(message.from_user.id, photo.file_id)
    await message.reply_text("✅ Custom thumbnail saved!")


# ---------------------------------------------------------------------------
# Handle any URL / Magnet sent by the user
# ---------------------------------------------------------------------------
@app.on_message(filters.text & filters.regex(r"(https?://\S+|magnet:\?xt=urn:btih:\S+)"))
async def leech_handler(client, message):
    url = message.text.strip()
    status = await message.reply_text(
        "🔍 **Adding to Aria2...**",
        parse_mode=enums.ParseMode.MARKDOWN,
    )

    user_id = message.from_user.id
    target_chat_id = get_dump_channel(user_id) or message.chat.id
    custom_caption = get_custom_caption(user_id) or ""
    custom_thumb_id = get_custom_thumb(user_id)

    # 1. Download via Aria2
    try:
        gid = await add_download(url, settings.DOWNLOAD_DIR)
        if not gid:
            await safe_edit(status, "❌ **Error:** Could not add to aria2.")
            return

        async def dl_progress(action, current, total, t0, speed=0, eta_seconds=0):
            # Using our local utils format_progress
            await safe_edit(status, format_progress(current, total, t0, action))

        await safe_edit(status, "⬇️ **Downloading...**")
        start_time = time.time()
        
        success, result_path_or_err = await monitor_download(gid, dl_progress, start_time)
        
        if not success:
            await safe_edit(status, f"❌ **Aria2 Error:** `{result_path_or_err}`")
            return
            
        filepath = result_path_or_err
        if not filepath or not os.path.exists(filepath):
            await safe_edit(status, "❌ **Error:** Download completed but file not found on disk.")
            return

        filename = os.path.basename(filepath)
        size = os.path.getsize(filepath)

        await safe_edit(status, "✂️ **Checking file size for splitting...**")
        
        # 2. Split file natively if > 1.9GB
        file_parts = await split_large_file(filepath)
        total_parts = len(file_parts)
        
        # 3. Download the custom thumb if set (we need a local file for upload)
        thumb_path = None
        if custom_thumb_id:
            thumb_path = await client.download_media(custom_thumb_id)

        upload_start = time.time()

        # 4. Upload each part
        for idx, part in enumerate(file_parts, start=1):
            part_size = os.path.getsize(part)
            part_name = os.path.basename(part)
            part_label = f"Part {idx}/{total_parts} " if total_parts > 1 else ""

            last_cb = [time.time()]

            async def up_progress(current, total,
                                  _label=part_label,
                                  _start=upload_start,
                                  _last=last_cb):
                now = time.time()
                if now - _last[0] >= FLOOD_COOLDOWN:
                    await safe_edit(
                        status,
                        format_progress(
                            current, total, _start,
                            f"Uploading {_label}"
                        ),
                    )
                    _last[0] = now

            caption_lines = [
                f"🏷 **{part_name}**",
                f"💾 {format_bytes(part_size)}",
            ]
            if total_parts > 1:
                caption_lines.append(f"📂 Part **{idx}** of **{total_parts}**")
            
            if custom_caption:
                caption_lines.append("")
                caption_lines.append(custom_caption)
                
            caption = "\n".join(caption_lines)

            send_kwargs = dict(
                chat_id=target_chat_id,
                caption=caption,
                progress=up_progress,
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            
            # If we are replying in the same chat, we can reply directly
            if target_chat_id == message.chat.id:
                send_kwargs["reply_to_message_id"] = message.id
                
            if thumb_path:
                send_kwargs["thumb"] = thumb_path

            # Auto upload as Document to prevent streaming bottlenecks and re-encoding
            await client.send_document(
                document=part,
                **send_kwargs,
            )

            # Brief delay between consecutive parts (anti-ban)
            if idx < total_parts:
                await asyncio.sleep(random.uniform(1.0, 2.5))

        await safe_edit(status, "✅ **All done!** 🎉")

    except Exception as exc:
        await safe_edit(status, f"❌ **Error:** `{str(exc)}`")

    finally:
        # Cleanup part files
        try:
            if 'file_parts' in locals():
                for p in file_parts:
                    if p != filepath and os.path.exists(p):
                        os.remove(p)
            if 'filepath' in locals() and filepath and os.path.exists(filepath):
                os.remove(filepath)
            if 'thumb_path' in locals() and thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Dummy web server — keeps Render/Heroku alive
# ---------------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="TG Leecher is alive!")

async def start_web_server():
    web_app = web.Application()
    web_app.add_routes([web.get("/", health_check)])
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.PORT).start()
    print(f"Web server started on port {settings.PORT}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main():
    start_aria2_daemon()
    await start_web_server()
    await app.start()
    print("Bot started. Listening for messages...")
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
