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
# Pyrogram Client — Bot Token mode (works up to 2 GB per part; we split above that)
# ---------------------------------------------------------------------------
app = Client(
    "leech_bot",
    api_id=settings.API_ID,
    api_hash=settings.API_HASH,
    bot_token=settings.BOT_TOKEN,
)

# ---------------------------------------------------------------------------
# In-memory store for pending upload choices (chat_msg_id → metadata)
# ---------------------------------------------------------------------------
pending: dict[int, dict] = {}

# Rate-limit tracker per message (msg_id → last edit timestamp)
_edit_ts: dict[int, float] = {}

COOLDOWN = 3.0  # minimum seconds between edits on the same message


async def safe_edit(msg: Message, text: str) -> None:
    """Edit message text with flood-control throttle (anti-ban)."""
    now = time.time()
    if now - _edit_ts.get(msg.id, 0) < COOLDOWN:
        return
    try:
        await msg.edit_text(text, parse_mode="markdown")
        _edit_ts[msg.id] = time.time()
    except Exception:
        pass  # Never crash on a rate-limit or 'message not modified'


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message) -> None:
    await message.reply_text(
        "🚀 **TG Leecher Bot**\n\n"
        "Send me **any** downloadable link and I'll leech it straight to Telegram!\n\n"
        "✅ Direct links, short links & complex redirect chains\n"
        "✂️ Auto-splits files **> 1.9 GB** into parts\n"
        "🎬 Choose **Document** or **Video** before upload\n"
        "🖼 Thumbnails auto-generated via ffmpeg\n"
        "⚡ Blazing fast — 2 MB chunks, concurrent I/O",
        parse_mode="markdown",
    )


# ---------------------------------------------------------------------------
# URL handler
# ---------------------------------------------------------------------------
@app.on_message(filters.text & filters.regex(r"https?://[^\s]+"))
async def leech_handler(client: Client, message: Message) -> None:
    url = message.text.strip()
    status = await message.reply_text("🔍 Resolving link…")

    # Small human-like delay (anti-ban)
    await asyncio.sleep(random.uniform(0.4, 1.2))

    filepath: str | None = None
    try:
        async def dl_cb(action, current, total, t0):
            await safe_edit(status, format_progress(current, total, t0, action))

        await safe_edit(status, "⬇️ **Downloading…**")
        filepath = await download_file(url, dl_cb)

        size = os.path.getsize(filepath)
        name = os.path.basename(filepath)

        # Fetch page title in parallel while we show the prompt
        page_title = await get_page_title(url)
        display_name = page_title or os.path.basename(filepath)

        # Store state so the callback can find it
        pending[message.id] = {
            "filepath": filepath,
            "source_url": url,
            "display_name": display_name,
            "status": status,
            "chat_id": message.chat.id,
            "reply_to": message.id,
        }

        await status.edit_text(
            f"✅ **Downloaded!**\n"
            f"🏷 **{display_name}**\n"
            f"📄 `{name}`\n"
            f"💾 {format_bytes(size)}\n\n"
            "📤 How would you like to upload?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📄 Document", callback_data=f"ul:doc:{message.id}"
                        ),
                        InlineKeyboardButton(
                            "🎬 Video", callback_data=f"ul:vid:{message.id}"
                        ),
                    ]
                ]
            ),
            parse_mode="markdown",
        )

    except Exception as exc:
        await safe_edit(status, f"❌ **Error:** `{exc}`")
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Upload callback — triggered when user taps Document or Video
# ---------------------------------------------------------------------------
@app.on_callback_query(filters.regex(r"^ul:(doc|vid):(\d+)$"))
async def upload_callback(client: Client, query: CallbackQuery) -> None:
    await query.answer()

    _, fmt, orig_id_str = query.data.split(":")
    orig_id = int(orig_id_str)

    entry = pending.pop(orig_id, None)
    if not entry:
        await query.message.edit_text("❌ Session expired. Please resend the link.")
        return

    filepath: str = entry["filepath"]
    source_url: str = entry["source_url"]
    display_name: str = entry["display_name"]
    status: Message = entry["status"]
    chat_id: int = entry["chat_id"]
    reply_to: int = entry["reply_to"]

    thumb_path: str | None = None
    parts: list[str] = []

    try:
        # 1. Split if needed
        await safe_edit(status, "✂️ **Checking file size…**")
        parts = split_file(filepath)
        total_parts = len(parts)

        # 2. Generate thumbnail (ffmpeg → og:image fallback)
        await safe_edit(status, "🖼 **Fetching thumbnail…**")
        thumb_path = await get_best_thumbnail(parts[0], source_url, settings.DOWNLOAD_DIR)

        upload_start = time.time()

        # 3. Upload each part
        for idx, part in enumerate(parts, start=1):
            part_size = os.path.getsize(part)
            label = f"Part {idx}/{total_parts} " if total_parts > 1 else ""

            last_edit = [time.time()]  # mutable so nested func can update

            async def up_cb(current, total,
                            _label=label, _start=upload_start,
                            _last=last_edit):
                now = time.time()
                if now - _last[0] >= COOLDOWN:
                    await safe_edit(
                        status,
                        format_progress(current, total, _start, f"Uploading {_label}"),
                    )
                    _last[0] = now

            caption = (
                f"🏷 **{display_name}**\n"
                f"📄 `{os.path.basename(part)}`\n"
                f"💾 {format_bytes(part_size)}"
            )
            if total_parts > 1:
                caption += f"\n📂 Part **{idx}** of **{total_parts}**"

            if fmt == "vid":
                await client.send_video(
                    chat_id=chat_id,
                    video=part,
                    caption=caption,
                    thumb=thumb_path,
                    supports_streaming=True,
                    reply_to_message_id=reply_to,
                    progress=up_cb,
                    parse_mode="markdown",
                )
            else:
                await client.send_document(
                    chat_id=chat_id,
                    document=part,
                    caption=caption,
                    thumb=thumb_path,
                    reply_to_message_id=reply_to,
                    progress=up_cb,
                    parse_mode="markdown",
                )

            # Small delay between parts to stay human-like
            if idx < total_parts:
                await asyncio.sleep(random.uniform(1.0, 2.5))

        await safe_edit(status, "✅ **Upload complete!** 🎉")

    except Exception as exc:
        await safe_edit(status, f"❌ **Upload error:** `{exc}`")

    finally:
        # Clean up part files (but not the original if no split happened)
        for p in parts:
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
# Dummy HTTP server — required by Render to keep the service alive
# ---------------------------------------------------------------------------
async def _health(request: web.Request) -> web.Response:
    return web.Response(text="TG Leecher is running! ✅")


async def _start_server() -> None:
    app_web = web.Application()
    app_web.add_routes([web.get("/", _health)])
    runner = web.AppRunner(app_web)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.PORT).start()
    print(f"🌐 Health server listening on port {settings.PORT}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    await _start_server()
    await app.start()
    print("✅ TG Leecher bot started.")
    await idle()
    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
