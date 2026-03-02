import os
import asyncio
import time
from typing import Optional, Callable

from pyrogram import Client
from pyrogram.types import Message
from pyrogram import enums

from config import settings
from utils import logger, format_progress, format_bytes, cleanup_file

# Anti-flood tracking
_last_edit_time = {}
FLOOD_COOLDOWN = 3.0


async def safe_edit_message(message, text: str, parse_mode=enums.ParseMode.MARKDOWN):
    """Edit a message with flood protection."""
    now = time.time()
    msg_id = message.id
    if now - _last_edit_time.get(msg_id, 0) < FLOOD_COOLDOWN:
        return
    try:
        await message.edit_text(text, parse_mode=parse_mode)
        _last_edit_time[msg_id] = time.time()
    except Exception as e:
        logger.debug(f"Failed to edit message: {e}")


class Uploader:
    """Telegram file uploader with progress tracking."""
    
    def __init__(self, client: Client):
        self.client = client
        self._upload_tasks = set()
    
    async def upload_file(
        self,
        chat_id: int,
        filepath: str,
        caption: str = "",
        thumb_path: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        progress_callback: Optional[Callable] = None,
        status_message=None,
        as_video: bool = False,
        video_duration: int = 0,
        video_width: int = 0,
        video_height: int = 0,
    ) -> Optional[Message]:
        """
        Upload a file to Telegram.
        
        Args:
            chat_id: Target chat ID
            filepath: Path to file to upload
            caption: Caption text
            thumb_path: Path to thumbnail image
            reply_to_message_id: Message ID to reply to
            progress_callback: Callback function(current, total)
            status_message: Optional message to edit with progress
            as_video: Whether to upload as video
            video_duration: Video duration in seconds
            video_width: Video width
            video_height: Video height
        
        Returns:
            Sent Message object or None
        """
        if not os.path.exists(filepath):
            logger.error(f"File not found: {filepath}")
            return None
        
        file_size = os.path.getsize(filepath)
        filename = os.path.basename(filepath)
        start_time = time.time()
        last_update = start_time
        
        async def progress_hook(current: int, total: int):
            nonlocal last_update
            now = time.time()
            
            # Call external callback
            if progress_callback:
                await progress_callback(current, total)
            
            # Update status message
            if status_message and (now - last_update >= FLOOD_COOLDOWN):
                try:
                    progress_text = format_progress(current, total, start_time, f"Uploading {filename}")
                    await safe_edit_message(status_message, progress_text)
                    last_update = now
                except Exception as e:
                    logger.debug(f"Progress update failed: {e}")
        
        try:
            send_kwargs = {
                "chat_id": chat_id,
                "caption": caption,
                "progress": progress_hook,
                "parse_mode": enums.ParseMode.MARKDOWN,
            }
            
            if reply_to_message_id:
                send_kwargs["reply_to_message_id"] = reply_to_message_id
            
            if thumb_path and os.path.exists(thumb_path):
                send_kwargs["thumb"] = thumb_path
            
            if as_video:
                # Upload as video
                send_kwargs["duration"] = video_duration
                send_kwargs["width"] = video_width
                send_kwargs["height"] = video_height
                
                message = await self.client.send_video(
                    video=filepath,
                    **send_kwargs
                )
            else:
                # Upload as document
                message = await self.client.send_document(
                    document=filepath,
                    **send_kwargs
                )
            
            logger.info(f"Successfully uploaded: {filename}")
            return message
            
        except Exception as e:
            logger.error(f"Upload failed for {filename}: {e}")
            raise
    
    async def upload_multiple(
        self,
        chat_id: int,
        filepaths: list[str],
        base_caption: str = "",
        thumb_path: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        progress_callback: Optional[Callable] = None,
        status_message=None,
        delay_between_uploads: float = 1.0,
    ) -> list[Optional[Message]]:
        """
        Upload multiple files with progress tracking.
        
        Args:
            chat_id: Target chat ID
            filepaths: List of file paths to upload
            base_caption: Base caption text (part info will be added)
            thumb_path: Path to thumbnail image
            reply_to_message_id: Message ID to reply to
            progress_callback: Callback for overall progress
            status_message: Optional message to edit with progress
            delay_between_uploads: Delay between uploads in seconds
        
        Returns:
            List of sent Message objects
        """
        results = []
        total_parts = len(filepaths)
        total_bytes = sum(os.path.getsize(f) for f in filepaths if os.path.exists(f))
        uploaded_bytes = 0
        
        for idx, filepath in enumerate(filepaths, start=1):
            if not os.path.exists(filepath):
                logger.error(f"File not found: {filepath}")
                results.append(None)
                continue
            
            part_name = os.path.basename(filepath)
            part_size = os.path.getsize(filepath)
            
            # Build caption
            caption_lines = [f"🏷 **{part_name}**", f"💾 {format_bytes(part_size)}"]
            if total_parts > 1:
                caption_lines.append(f"📂 Part **{idx}** of **{total_parts}**")
            if base_caption:
                caption_lines.append("")
                caption_lines.append(base_caption)
            caption = "\n".join(caption_lines)
            
            # Individual file progress
            async def file_progress(current: int, total: int):
                nonlocal uploaded_bytes
                uploaded_bytes = sum(
                    os.path.getsize(filepaths[i]) for i in range(idx - 1) if os.path.exists(filepaths[i])
                ) + current
                
                if progress_callback:
                    await progress_callback(uploaded_bytes, total_bytes)
            
            try:
                message = await self.upload_file(
                    chat_id=chat_id,
                    filepath=filepath,
                    caption=caption,
                    thumb_path=thumb_path,
                    reply_to_message_id=reply_to_message_id if idx == 1 else None,
                    progress_callback=file_progress,
                    status_message=status_message,
                )
                results.append(message)
                
                # Delay between uploads (except for the last one)
                if idx < total_parts:
                    await asyncio.sleep(delay_between_uploads)
                    
            except Exception as e:
                logger.error(f"Failed to upload part {idx}: {e}")
                results.append(None)
        
        return results


# Legacy function for backward compatibility
async def upload_to_telegram(
    client: Client,
    filepath: str,
    chat_id: Optional[int] = None,
    progress_callback: Optional[Callable] = None,
) -> Optional[Message]:
    """
    Legacy upload function for compatibility.
    
    Args:
        client: Pyrogram client instance
        filepath: Path to file
        chat_id: Target chat ID (defaults to OWNER_ID)
        progress_callback: Progress callback function
    
    Returns:
        Sent Message or None
    """
    uploader = Uploader(client)
    return await uploader.upload_file(
        chat_id=chat_id or settings.OWNER_ID,
        filepath=filepath,
        progress_callback=progress_callback,
    )


def cleanup(filepath: str):
    """Legacy cleanup function."""
    cleanup_file(filepath)
