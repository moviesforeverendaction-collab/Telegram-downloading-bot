import os
import time
import asyncio
import random
import datetime

from aiohttp import web
from pyrogram import Client, filters, idle, enums
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
    extract_video_metadata,
    clean_title,
    get_best_thumbnail,
    get_page_title,
    format_progress,
    format_bytes,
    format_duration,
)

# ---------------------------------------------------------------------------
# Pyrogram Bot — more workers = faster upload parallelism
# ---------------------------------------------------------------------------
app = Client(
    "leech_bot",
    api_id=settings.API_ID,
    api_hash=settings.API_HASH,
    bot_token=settings.BOT_TOKEN,
    workers=16,
)

# pending[orig_message_id] = { ... }
pending = {}

_last_edit_time = {}
FLOOD_COOLDOWN = 3.0

# Video file extensions (for ffprobe metadata + poster lookup)
VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".webm", ".m4v", ".ts", ".m2ts", ".mpeg", ".3gp",
}


def is_video(filepath):
    _, ext = os.path.splitext(filepath.lower())
    return ext in VIDEO_EXTS


def now_ist():
    """Return current time formatted in IST."""
    utc = datetime.datetime.utcnow()
    ist = utc + datetime.timedelta(hours=5, minutes=30)
    return ist.strftime("%d %b %Y, %I:%M %p IST")


def build_caption(display_name, filename, filesize, meta, total_parts=1, part_idx=1):
    """
    Build a rich HTML caption with quoted title, tech specs, and download time.
    Stays within Telegram's 1024-char caption limit.
    """
    lines = []

    # Title line with quotes
    lines.append('🎬 <b>"{}"</b>'.format(display_name))
    lines.append("")

    # Filename + size
    lines.append("📄 <code>{}</code>".format(filename))

    size_str = format_bytes(filesize)
    dur_str = format_duration(meta.get("duration")) if meta.get("duration") else None
    if dur_str and dur_str != "Unknown":
        lines.append("💾 <b>{}</b>  ·  ⏱ <b>{}</b>".format(size_str, dur_str))
    else:
        lines.append("💾 <b>{}</b>".format(size_str))

    # Technical info block (only if we have data)
    w = meta.get("width")
    h = meta.get("height")
    vc = meta.get("video_codec")
    ac = meta.get("audio_codec")
    bk = meta.get("bitrate_kbps")

    tech_lines = []
    if w and h and vc:
        res_label = ""
        if h >= 2160:
            res_label = " (4K)"
        elif h >= 1080:
            res_label = " (1080p)"
        elif h >= 720:
            res_label = " (720p)"
        tech_lines.append("├ 🖥 {}×{}{}  ·  🎞 {}".format(w, h, res_label, vc))
    if ac:
        bk_str = "  ·  ⚡ {} Kbps".format(bk) if bk else ""
        tech_lines.append("└ 🔊 {}{}".format(ac, bk_str))

    if tech_lines:
        lines.append("")
        lines.append("📊 <b>Media Info</b>")
        lines.append("<code>{}</code>".format("\n".join(tech_lines)))

    # Parts info
    if total_parts > 1:
        lines.append("")
        lines.append("📂 Part <b>{}</b> of <b>{}</b>".format(part_idx, total_parts))

    # Download timestamp
    lines.append("")
    lines.append("📥 <i>Downloaded: {}</i>".format(now_ist()))
    lines.append("🤖 <i>TG Leecher Bot</i>")

    caption = "\n".join(lines)

    # Hard cap at 1024 chars (Telegram limit for captions)
    if len(caption) > 1020:
        caption = caption[:1020] + "…"

    return caption


# ---------------------------------------------------------------------------
# Safe throttled message editor
# ---------------------------------------------------------------------------

async def safe_edit(msg, text, parse_mode=enums.ParseMode.HTML):
    now = time.time()
    if now - _last_edit_time.get(msg.id, 0) < FLOOD_COOLDOWN:
        return
    try:
        await msg.edit_text(text, parse_mode=parse_mode)
        _last_edit_time[msg.id] = time.time()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text(
        "🚀 <b>TG Leecher Bot</b>\n\n"
        "Send me any downloadable link!\n\n"
        "✅ Direct links, short links &amp; complex redirects\n"
        "✂️ Auto-splits files <b>&gt; 1.9 GB</b> into numbered parts\n"
        "🎬 Upload as <b>Document</b> or <b>Video</b> — your choice\n"
        "🖼 Movie/Series posters via iTunes API + ffmpeg\n"
        "📊 Full metadata: resolution, codec, bitrate, duration\n"
        "⚡ Fast: 4 MB chunks, 16 workers",
        parse_mode=enums.ParseMode.HTML,
    )


# ---------------------------------------------------------------------------
# URL handler
# ---------------------------------------------------------------------------

@app.on_message(filters.text & filters.regex(r"https?://\S+"))
async def leech_handler(client, message):
    url = message.text.strip()
    status = await message.reply_text(
        "🔍 <b>Resolving link...</b>",
        parse_mode=enums.ParseMode.HTML,
    )

    await asyncio.sleep(random.uniform(0.5, 1.5))

    filepath = None
    try:
        async def dl_progress(action, current, total, t0):
            await safe_edit(status, format_progress(current, total, t0, action))

        await safe_edit(status, "⬇️ <b>Downloading...</b>")
        filepath = await download_file(url, dl_progress)

        filesize = os.path.getsize(filepath)
        filename = os.path.basename(filepath)

        # Derive display name: page title → filename-based title
        page_title = await get_page_title(url)
        if page_title:
            display_name = page_title
        else:
            display_name = clean_title(filename)

        pending[message.id] = {
            "filepath": filepath,
            "source_url": url,
            "display_name": display_name,
            "filename": filename,
            "filesize": filesize,
            "status": status,
            "chat_id": message.chat.id,
            "reply_to": message.id,
        }

        await status.edit_text(
            "✅ <b>Download complete!</b>\n"
            "🏷 <b>\"{}\"</b>\n"
            "📄 <code>{}</code>\n"
            "💾 <b>{}</b>\n\n"
            "📤 How would you like to upload?".format(
                display_name, filename, format_bytes(filesize)
            ),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📄 Document",
                        callback_data="ul:doc:{}".format(message.id),
                    ),
                    InlineKeyboardButton(
                        "🎬 Video",
                        callback_data="ul:vid:{}".format(message.id),
                    ),
                ]
            ]),
            parse_mode=enums.ParseMode.HTML,
        )

    except Exception as exc:
        await safe_edit(
            status,
            "❌ <b>Error:</b> <code>{}</code>".format(str(exc)),
        )
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Upload callback
# ---------------------------------------------------------------------------

@app.on_callback_query(filters.regex(r"^ul:(doc|vid):(\d+)$"))
async def upload_callback(client, query):
    await query.answer()

    parts_of_data = query.data.split(":")
    fmt = parts_of_data[1]
    orig_id = int(parts_of_data[2])

    entry = pending.pop(orig_id, None)
    if not entry:
        try:
            await query.message.edit_text(
                "❌ Session expired. Please resend the link.",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
        return

    filepath = entry["filepath"]
    source_url = entry["source_url"]
    display_name = entry["display_name"]
    filename = entry["filename"]
    filesize = entry["filesize"]
    status = entry["status"]
    chat_id = entry["chat_id"]
    reply_to = entry["reply_to"]

    thumb_path = None
    file_parts = []
    meta = {}

    try:
        # 1. Split if needed
        await safe_edit(status, "✂️ <b>Checking file size...</b>")
        file_parts = split_file(filepath)
        total_parts = len(file_parts)

        # 2. Extract video metadata (duration, codec, resolution, bitrate)
        if is_video(filepath):
            await safe_edit(status, "📊 <b>Reading media info...</b>")
            meta = await extract_video_metadata(file_parts[0])
        
        # 3. Fetch poster / thumbnail
        await safe_edit(status, "🖼 <b>Fetching poster...</b>")
        clean_movie_title = clean_title(filename) if not display_name else display_name
        thumb_path = await get_best_thumbnail(
            file_parts[0],
            source_url,
            settings.DOWNLOAD_DIR,
            title=clean_movie_title if is_video(filepath) else None,
        )

        upload_start = time.time()

        # 4. Upload each part
        for idx, part in enumerate(file_parts, start=1):
            part_size = os.path.getsize(part)
            part_name = os.path.basename(part)
            part_label = "Part {}/{} ".format(idx, total_parts) if total_parts > 1 else ""

            last_cb = [time.time()]

            async def up_progress(current, total,
                                  _label=part_label,
                                  _start=upload_start,
                                  _last=last_cb):
                now = time.time()
                if now - _last[0] >= FLOOD_COOLDOWN:
                    await safe_edit(
                        status,
                        format_progress(current, total, _start,
                                        "Uploading {}".format(_label)),
                    )
                    _last[0] = now

            caption = build_caption(
                display_name, part_name, part_size, meta,
                total_parts=total_parts, part_idx=idx,
            )

            send_kwargs = dict(
                chat_id=chat_id,
                caption=caption,
                reply_to_message_id=reply_to,
                progress=up_progress,
                parse_mode=enums.ParseMode.HTML,
            )
            if thumb_path:
                send_kwargs["thumb"] = thumb_path

            if fmt == "vid":
                # Pass duration, width, height so Telegram shows correct playback info
                if meta.get("duration"):
                    send_kwargs["duration"] = meta["duration"]
                if meta.get("width"):
                    send_kwargs["width"] = meta["width"]
                if meta.get("height"):
                    send_kwargs["height"] = meta["height"]

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

            if idx < total_parts:
                await asyncio.sleep(random.uniform(1.0, 2.5))

        await safe_edit(status, "✅ <b>All done!</b> 🎉")

    except Exception as exc:
        await safe_edit(
            status,
            "❌ <b>Upload error:</b> <code>{}</code>".format(str(exc)),
        )

    finally:
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
# Health server for Render
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
# Entry point — MUST be app.run(), not asyncio.run()
# ---------------------------------------------------------------------------

async def main():
    await start_web_server()
    await app.start()
    print("Bot started.")
    await idle()
    await app.stop()


if __name__ == "__main__":
    app.run(main())
