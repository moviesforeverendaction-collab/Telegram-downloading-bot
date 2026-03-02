import os
import time
import asyncio
import random

from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from config import settings
from utils import (
    download_file,
    split_file,
    get_best_thumbnail,
    get_page_title,
    format_progress,
    format_bytes,
)

# ---------------------------------------------------------------------------
# Pyrogram Bot Client
# ---------------------------------------------------------------------------
app = Client(
    "leech_bot",
    api_id=settings.API_ID,
    api_hash=settings.API_HASH,
    bot_token=settings.BOT_TOKEN,
)

# ---------------------------------------------------------------------------
# State: pending download entries waiting for format choice
# pending[orig_message_id] = { filepath, source_url, display_name, status, chat_id, reply_to }
# ---------------------------------------------------------------------------
pending = {}

# Anti-flood: track last edit time per message id
_last_edit_time = {}
FLOOD_COOLDOWN = 3.0  # seconds between message edits


async def safe_edit(msg, text):
    """
    Edit a message — but throttle to once per FLOOD_COOLDOWN seconds.
    Silently drops the edit if called too fast (anti-flood, anti-ban).
    """
    now = time.time()
    msg_id = msg.id
    if now - _last_edit_time.get(msg_id, 0) < FLOOD_COOLDOWN:
        return
    try:
        await msg.edit_text(text, parse_mode="markdown")
        _last_edit_time[msg_id] = time.time()
    except Exception:
        pass  # 'message not modified' or rate limit — never crash here


# ---------------------------------------------------------------------------
# /start command
# ---------------------------------------------------------------------------
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text(
        "🚀 **TG Leecher Bot**\n\n"
        "Send me any downloadable link!\n\n"
        "✅ Direct links, short links & complex redirect chains\n"
        "✂️ Auto-splits files **> 1.9 GB** into numbered parts\n"
        "🎬 Upload as **Document** or **Video** — your choice\n"
        "🖼 Thumbnails via ffmpeg or Online OG image\n"
        "⚡ Fast: 2 MB download chunks",
        parse_mode="markdown",
    )


# ---------------------------------------------------------------------------
# Handle any URL sent by the user
# ---------------------------------------------------------------------------
@app.on_message(filters.text & filters.regex(r"https?://\S+"))
async def leech_handler(client, message):
    url = message.text.strip()
    status = await message.reply_text("🔍 **Resolving link...**", parse_mode="markdown")

    # Human-like delay (anti-ban)
    await asyncio.sleep(random.uniform(0.5, 1.5))

    filepath = None
    try:
        async def dl_progress(action, current, total, t0):
            await safe_edit(status, format_progress(current, total, t0, action))

        await safe_edit(status, "⬇️ **Downloading...**")
        filepath = await download_file(url, dl_progress)

        size = os.path.getsize(filepath)
        filename = os.path.basename(filepath)

        # Fetch the page title from the source URL in parallel
        page_title = await get_page_title(url)
        display_name = page_title if page_title else filename

        # Store everything for the callback
        pending[message.id] = {
            "filepath": filepath,
            "source_url": url,
            "display_name": display_name,
            "filename": filename,
            "status": status,
            "chat_id": message.chat.id,
            "reply_to": message.id,
        }

        # Ask user: Document or Video?
        await status.edit_text(
            "✅ **Download complete!**\n"
            "🏷 **{}**\n"
            "📄 `{}`\n"
            "💾 {}\n\n"
            "📤 How would you like to upload?".format(display_name, filename, format_bytes(size)),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📄 Document", callback_data="ul:doc:{}".format(message.id)),
                    InlineKeyboardButton("🎬 Video",    callback_data="ul:vid:{}".format(message.id)),
                ]
            ]),
            parse_mode="markdown",
        )

    except Exception as exc:
        err = str(exc)
        await safe_edit(status, "❌ **Error:** `{}`".format(err))
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Callback: user chose Document or Video
# ---------------------------------------------------------------------------
@app.on_callback_query(filters.regex(r"^ul:(doc|vid):(\d+)$"))
async def upload_callback(client, query):
    await query.answer()

    parts_of_data = query.data.split(":")
    fmt = parts_of_data[1]           # "doc" or "vid"
    orig_id = int(parts_of_data[2])

    entry = pending.pop(orig_id, None)
    if not entry:
        try:
            await query.message.edit_text("❌ Session expired. Please send the link again.")
        except Exception:
            pass
        return

    filepath = entry["filepath"]
    source_url = entry["source_url"]
    display_name = entry["display_name"]
    status = entry["status"]
    chat_id = entry["chat_id"]
    reply_to = entry["reply_to"]

    thumb_path = None
    file_parts = []

    try:
        # Step 1: Split if needed
        await safe_edit(status, "✂️ **Checking file size...**")
        file_parts = split_file(filepath)
        total_parts = len(file_parts)

        # Step 2: Thumbnail
        await safe_edit(status, "🖼 **Fetching thumbnail...**")
        thumb_path = await get_best_thumbnail(file_parts[0], source_url, settings.DOWNLOAD_DIR)

        upload_start = time.time()

        # Step 3: Upload each part
        for idx, part in enumerate(file_parts, start=1):
            part_size = os.path.getsize(part)
            part_name = os.path.basename(part)
            part_label = "Part {}/{} ".format(idx, total_parts) if total_parts > 1 else ""

            # Mutable container so the inner async func can update it
            last_cb = [time.time()]

            async def up_progress(current, total,
                                  _label=part_label,
                                  _start=upload_start,
                                  _last=last_cb):
                now = time.time()
                if now - _last[0] >= FLOOD_COOLDOWN:
                    await safe_edit(
                        status,
                        format_progress(current, total, _start, "Uploading {}".format(_label))
                    )
                    _last[0] = now

            caption_lines = [
                "🏷 **{}**".format(display_name),
                "📄 `{}`".format(part_name),
                "💾 {}".format(format_bytes(part_size)),
            ]
            if total_parts > 1:
                caption_lines.append("📂 Part **{}** of **{}**".format(idx, total_parts))
            caption = "\n".join(caption_lines)

            send_kwargs = dict(
                chat_id=chat_id,
                caption=caption,
                reply_to_message_id=reply_to,
                progress=up_progress,
                parse_mode="markdown",
            )
            if thumb_path:
                send_kwargs["thumb"] = thumb_path

            if fmt == "vid":
                await client.send_video(
                    video=part,
                    supports_streaming=True,
                    **send_kwargs,
                )
            else:
                await client.send_document(
                    document=part,
                    **send_kwargs,
                )

            # Brief delay between parts (anti-ban)
            if idx < total_parts:
                await asyncio.sleep(random.uniform(1.0, 2.5))

        await safe_edit(status, "✅ **All done!** 🎉")

    except Exception as exc:
        await safe_edit(status, "❌ **Upload error:** `{}`".format(str(exc)))

    finally:
        # Cleanup: remove part files (original is same as part[0] if no split)
        for p in file_parts:
            if p != filepath and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        if thumb_path and os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Dummy web server — keeps Render from killing the service
# ---------------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="TG Leecher is alive!")


async def start_web_server():
    web_app = web.Application()
    web_app.add_routes([web.get("/", health_check)])
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.PORT).start()
    print("Web server started on port {}".format(settings.PORT))


# ---------------------------------------------------------------------------
# Main entry point
# IMPORTANT: Must use app.run() — NOT asyncio.run() — with Pyrogram
# ---------------------------------------------------------------------------
async def main():
    await start_web_server()
    await app.start()
    print("Bot started. Listening for messages...")
    await idle()
    await app.stop()


if __name__ == "__main__":
    app.run(main())
