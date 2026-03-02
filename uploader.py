import os
from pyrogram import Client
from config import settings

# Initialize Pyrogram client
app = Client(
    "leech_bot",
    api_id=settings.API_ID,
    api_hash=settings.API_HASH,
    bot_token=settings.BOT_TOKEN
)

async def upload_to_telegram(filepath: str, progress_callback=None):
    async def pyrogram_progress(current, total):
        if progress_callback:
            await progress_callback("uploading", current, total)

    async with app:
        # Assuming we are sending to the OWNER_ID for now
        # The bot must have been started by the OWNER_ID first
        message = await app.send_document(
            chat_id=settings.OWNER_ID,
            document=filepath,
            progress=pyrogram_progress
        )
        return message

def cleanup(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        print(f"Cleanup error: {e}")
