import re
import os
import time
import asyncio
import subprocess
import aiohttp
import logging

from urllib.parse import urlparse
from config import settings

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Browser-like headers — tricks most file hosts into responding normally
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_bytes(size):
    """Return human-readable byte size string."""
    if size == 0:
        return "0 B"
    size = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def format_speed(bps):
    """Format speed in bytes per second."""
    if bps == 0:
        return "0 B/s"
    return format_bytes(bps) + "/s"


def format_eta(seconds):
    """Format ETA in human-readable format."""
    if seconds <= 0 or seconds > 86400:
        return "∞"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def format_progress(current, total, start_time, action):
    """Render a rich progress bar string for Telegram."""
    elapsed = time.time() - start_time
    speed = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / speed if speed > 0 else 0
    pct = (current / total * 100.0) if total > 0 else 0.0
    filled = int(pct / 5)
    filled = min(filled, 20)
    bar = "█" * filled + "░" * (20 - filled)
    icon = "⬇️" if "Download" in action else "⬆️"
    return (
        f"{icon} **{action}**\n"
        f"`{bar}` {pct:.1f}%\n"
        f"📦 {format_bytes(current)} / {format_bytes(total)}\n"
        f"⚡ {format_speed(speed)}  |  ⏱ ETA: {format_eta(remaining)}"
    )


def format_progress_json(current, total, start_time, action):
    """Format progress data for WebSocket JSON messages."""
    elapsed = time.time() - start_time
    speed = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / speed if speed > 0 else 0
    pct = (current / total * 100.0) if total > 0 else 0.0
    return {
        "action": action,
        "current": current,
        "total": total,
        "percentage": round(pct, 2),
        "speed": int(speed),
        "speed_formatted": format_speed(speed),
        "eta_seconds": int(remaining),
        "eta_formatted": format_eta(remaining),
        "elapsed_seconds": int(elapsed),
        "current_formatted": format_bytes(current),
        "total_formatted": format_bytes(total),
    }


# ---------------------------------------------------------------------------
# File utilities
# ---------------------------------------------------------------------------

def cleanup_file(filepath: str):
    """Safely remove a file if it exists."""
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Cleaned up file: {filepath}")
    except Exception as e:
        logger.error(f"Error cleaning up file {filepath}: {e}")


def get_unique_filename(directory: str, filename: str) -> str:
    """Generate a unique filename in the given directory."""
    base, ext = os.path.splitext(filename)
    filepath = os.path.join(directory, filename)
    counter = 1
    while os.path.exists(filepath):
        filename = f"{base}_{counter}{ext}"
        filepath = os.path.join(directory, filename)
        counter += 1
    return filepath


def clean_filename(filename: str) -> str:
    """Remove invalid characters from filename."""
    bad_chars = '\\/|:*?"<> '
    cleaned = "".join(c for c in filename if c not in bad_chars)
    return cleaned if cleaned else "downloaded_file"


# ---------------------------------------------------------------------------
# Video utilities
# ---------------------------------------------------------------------------

def get_video_info(filepath: str) -> dict:
    """Extract video metadata using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", filepath
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        import json
        data = json.loads(result.stdout)
        
        video_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break
        
        if video_stream:
            return {
                "duration": float(video_stream.get("duration", 0)),
                "width": video_stream.get("width", 0),
                "height": video_stream.get("height", 0),
                "codec": video_stream.get("codec_name", "unknown"),
            }
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
    
    return {}


def generate_thumbnail(video_path: str, output_path: str, time_offset: str = "00:00:05") -> bool:
    """Generate thumbnail from video using ffmpeg."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-i", video_path, "-ss", time_offset,
                "-vframes", "1", "-q:v", "2", "-y", output_path
            ],
            capture_output=True,
            timeout=30
        )
        return result.returncode == 0 and os.path.exists(output_path)
    except Exception as e:
        logger.error(f"Error generating thumbnail: {e}")
        return False


# ---------------------------------------------------------------------------
# Poster fetching
# ---------------------------------------------------------------------------

async def fetch_itunes_poster(title: str) -> str:
    """Fetch movie/series poster from iTunes API."""
    try:
        # Clean title for search
        clean_title = re.sub(r'\([^)]*\)|\[[^\]]*\]', '', title).strip()
        clean_title = re.sub(r'[^\w\s]', '', clean_title)
        
        url = f"https://itunes.apple.com/search?term={clean_title.replace(' ', '+')}&media=movie&entity=movie&limit=1"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("resultCount", 0) > 0:
                        artwork = data["results"][0].get("artworkUrl100", "")
                        # Get high-res version
                        return artwork.replace("100x100", "600x600")
    except Exception as e:
        logger.error(f"Error fetching poster: {e}")
    
    return ""


# ---------------------------------------------------------------------------
# Async file operations
# ---------------------------------------------------------------------------

async def async_copy_file(src: str, dst: str, chunk_size: int = 1024 * 1024):
    """Asynchronously copy a file in chunks."""
    import aiofiles
    async with aiofiles.open(src, 'rb') as fsrc:
        async with aiofiles.open(dst, 'wb') as fdst:
            while True:
                chunk = await fsrc.read(chunk_size)
                if not chunk:
                    break
                await fdst.write(chunk)
