import re
import os
import time
import asyncio
import subprocess
import aiohttp

from urllib.parse import urlparse
from config import settings

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
    size = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def format_speed(bps):
    return format_bytes(bps) + "/s"


def format_eta(seconds):
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


# ---------------------------------------------------------------------------
# URL resolver — follows all redirects, extracts real filename
# ---------------------------------------------------------------------------

async def resolve_final_url(url):
    """
    Follow all redirects and return (final_url, filename).
    Works for direct links, short links, and PHP redirect pages.
    """
    timeout = aiohttp.ClientTimeout(total=60, connect=15)
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        async with session.get(url, allow_redirects=True) as resp:
            resp.raise_for_status()
            final_url = str(resp.url)

            # Try Content-Disposition header first
            cd = resp.headers.get("Content-Disposition", "")
            filename = ""
            if "filename=" in cd:
                part = cd.split("filename=")[-1].strip().strip("\"'")
                filename = part.split(";")[0].strip()

            # Try URL path
            if not filename:
                path = urlparse(final_url).path
                name = os.path.basename(path)
                if name and "." in name:
                    filename = name

            # Fallback: guess from Content-Type
            if not filename or "." not in filename:
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
                ext = ctype.split(";")[0].split("/")[-1]
                if ext in ("octet-stream", "force-download", "x-download", "binary"):
                    ext = "bin"
                filename = f"leech_file.{ext}"

    return final_url, filename


# ---------------------------------------------------------------------------
# Downloader — 2 MB chunks, streaming to disk
# ---------------------------------------------------------------------------

async def download_file(url, progress_callback=None):
    """Download file from any URL to DOWNLOAD_DIR. Returns local filepath."""
    final_url, filename = await resolve_final_url(url)

    # Sanitize filename — strip invalid chars
    bad_chars = set('\\/|:*?"<>')
    filename = "".join(c for c in filename if c not in bad_chars).strip()
    if not filename:
        filename = "leech_file"

    filepath = os.path.join(settings.DOWNLOAD_DIR, filename)

    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=120)
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        async with session.get(final_url, allow_redirects=True) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            start_time = time.time()
            last_update = start_time

            with open(filepath, "wb") as f:
                async for chunk in resp.content.iter_chunked(2 * 1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if progress_callback and (now - last_update >= 3.0):
                        await progress_callback("Downloading", downloaded, total, start_time)
                        last_update = now

    return filepath


# ---------------------------------------------------------------------------
# File splitter
# ---------------------------------------------------------------------------

def split_file(filepath):
    """
    Split a file into <= SPLIT_SIZE chunks.
    Returns list of paths. Single-item list if no split needed.
    """
    file_size = os.path.getsize(filepath)
    if file_size <= settings.SPLIT_SIZE:
        return [filepath]

    parts = []
    base, ext = os.path.splitext(filepath)
    part_num = 1

    with open(filepath, "rb") as src:
        while True:
            data = src.read(settings.SPLIT_SIZE)
            if not data:
                break
            part_path = "{}.part{:03d}{}".format(base, part_num, ext)
            with open(part_path, "wb") as dst:
                dst.write(data)
            parts.append(part_path)
            part_num += 1

    return parts


# ---------------------------------------------------------------------------
# Thumbnail — ffmpeg local frame, then OG image fallback
# ---------------------------------------------------------------------------

async def get_thumbnail_ffmpeg(filepath):
    """Extract a video frame at 5 seconds using ffmpeg. Returns path or None."""
    thumb_path = filepath + ".thumb.jpg"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", filepath,
            "-ss", "00:00:05",
            "-vframes", "1",
            "-vf", "scale=320:-1",
            thumb_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except (FileNotFoundError, OSError):
        pass  # ffmpeg not installed
    except Exception:
        pass
    return None


async def get_thumbnail_online(source_url, download_dir):
    """
    Scrape og:image / twitter:image from source page.
    Downloads the image and saves it as a local JPEG. Returns path or None.
    """
    thumb_path = os.path.join(download_dir, "_og_thumb.jpg")
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(source_url, allow_redirects=True) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if "text" not in ctype:
                    return None  # Direct binary — no HTML to scrape
                html = await resp.text(errors="ignore")

        # Parse OG / twitter image tags
        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        ]
        img_url = None
        for pattern in patterns:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                img_url = m.group(1).strip()
                break

        if not img_url:
            return None

        # Make relative URLs absolute
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("/"):
            parsed = urlparse(source_url)
            img_url = "{}://{}{}".format(parsed.scheme, parsed.netloc, img_url)

        # Download the image
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(img_url) as img_resp:
                if img_resp.status == 200:
                    data = await img_resp.read()
                    if data:
                        with open(thumb_path, "wb") as f:
                            f.write(data)
                        return thumb_path

    except Exception:
        pass

    return None


async def get_best_thumbnail(filepath, source_url, download_dir):
    """
    Best-effort thumbnail: ffmpeg → og:image → None.
    Never raises; always returns a path string or None.
    """
    thumb = await get_thumbnail_ffmpeg(filepath)
    if thumb:
        return thumb
    thumb = await get_thumbnail_online(source_url, download_dir)
    return thumb  # May be None — callers must handle that


# ---------------------------------------------------------------------------
# Page title extractor
# ---------------------------------------------------------------------------

async def get_page_title(url):
    """
    Return og:title or <title> from the source URL's HTML.
    Returns None on any failure — never raises.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if "text" not in ctype:
                    return None
                html = await resp.text(errors="ignore")

        # og:title first (cleaner, no site branding)
        m = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
        if m:
            return m.group(1).strip()

        # Fallback to <title>
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    except Exception:
        pass

    return None
