import aiohttp
import asyncio
import os
import time
from urllib.parse import urlparse
from config import settings

# Browser-like headers to bypass bot blockers and resolve complex/short links
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_bytes(size: int) -> str:
    """Human-readable byte size."""
    power = 2 ** 10
    n = 0
    labels = {0: "B", 1: "KB", 2: "MB", 3: "GB", 4: "TB"}
    while size >= power and n < 4:
        size /= power
        n += 1
    return f"{size:.2f} {labels[n]}"


def format_speed(speed: float) -> str:
    return f"{format_bytes(int(speed))}/s"


def format_eta(seconds: float) -> str:
    if seconds < 0 or seconds > 86400:
        return "∞"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def format_progress(current: int, total: int, start_time: float, action: str) -> str:
    """Full progress block with bar, speed, and ETA."""
    elapsed = time.time() - start_time
    speed = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / speed if speed > 0 else 0
    pct = (current / total * 100) if total else 0
    filled = int(pct / 5)
    bar = "█" * filled + "░" * (20 - filled)
    icon = "⬇️" if "Download" in action else "⬆️"
    return (
        f"{icon} **{action}**\n"
        f"`{bar}` {pct:.1f}%\n"
        f"📦 {format_bytes(current)} / {format_bytes(total)}\n"
        f"⚡ {format_speed(speed)}  |  ⏱ ETA: {format_eta(remaining)}"
    )


# ---------------------------------------------------------------------------
# URL resolution — follows redirects, extracts real filename
# ---------------------------------------------------------------------------

async def resolve_final_url(url: str) -> tuple:
    """
    Follow all HTTP redirects (including PHP redirect pages like adl.php?id=...)
    and return (final_url, filename).
    Falls back gracefully if Content-Disposition is missing.
    """
    connector = aiohttp.TCPConnector(limit=32, ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=60, connect=15)

    async with aiohttp.ClientSession(
        headers=HEADERS, connector=connector, timeout=timeout
    ) as session:
        async with session.get(url, allow_redirects=True) as resp:
            resp.raise_for_status()
            final_url = str(resp.url)

            # 1. Try Content-Disposition: attachment; filename="foo.mp4"
            cd = resp.headers.get("Content-Disposition", "")
            filename = ""
            if "filename=" in cd:
                part = cd.split("filename=")[-1].strip().strip("\"'")
                filename = part.split(";")[0].strip()

            # 2. Try the path component of the final URL
            if not filename:
                path = urlparse(final_url).path
                name = os.path.basename(path)
                if name and "." in name:
                    filename = name

            # 3. Fallback: use content-type to guess extension
            if not filename or "." not in filename:
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
                ext = ctype.split(";")[0].split("/")[-1]
                ext = ext if ext not in ("octet-stream", "force-download") else "bin"
                filename = f"leech_file.{ext}"

    return final_url, filename


# ---------------------------------------------------------------------------
# Downloader — high-speed streaming with progress
# ---------------------------------------------------------------------------

async def download_file(url: str, progress_callback=None) -> str:
    """Download any URL to DOWNLOAD_DIR. Returns local filepath."""
    final_url, filename = await resolve_final_url(url)

    # Sanitize filename
    filename = "".join(c for c in filename if c not in r'\/:*?"<>|').strip()
    if not filename:
        filename = "leech_file"

    filepath = os.path.join(settings.DOWNLOAD_DIR, filename)

    connector = aiohttp.TCPConnector(limit=32, ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)

    async with aiohttp.ClientSession(
        headers=HEADERS, connector=connector, timeout=timeout
    ) as session:
        async with session.get(final_url, allow_redirects=True) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            start_time = time.time()
            last_update = start_time

            with open(filepath, "wb") as f:
                async for chunk in resp.content.iter_chunked(2 * 1024 * 1024):  # 2 MB
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if progress_callback and (now - last_update >= 3.0):
                        await progress_callback("Downloading", downloaded, total, start_time)
                        last_update = now

    return filepath


# ---------------------------------------------------------------------------
# File splitter — splits files > SPLIT_SIZE into numbered parts
# ---------------------------------------------------------------------------

def split_file(filepath: str) -> list:
    """
    Split a file into chunks of settings.SPLIT_SIZE bytes.
    Returns a list of file paths (single-element list if no split needed).
    All parts are written to the same directory as the original file.
    """
    file_size = os.path.getsize(filepath)
    if file_size <= settings.SPLIT_SIZE:
        return [filepath]

    parts = []
    base, ext = os.path.splitext(filepath)
    part_num = 1

    with open(filepath, "rb") as src:
        while True:
            chunk = src.read(settings.SPLIT_SIZE)
            if not chunk:
                break
            part_path = f"{base}.part{part_num:03d}{ext}"
            with open(part_path, "wb") as dst:
                dst.write(chunk)
            parts.append(part_path)
            part_num += 1

    return parts


# ---------------------------------------------------------------------------
# Thumbnail engine — ffmpeg first, then Open Graph image scraping as fallback
# ---------------------------------------------------------------------------

async def get_thumbnail(filepath: str) -> str | None:
    """
    Try to get a thumbnail for a file.
    Strategy 1: Run ffmpeg to extract a frame (works for video files).
    Returns the thumbnail path, or None if ffmpeg fails.
    """
    thumb_path = filepath + ".thumb.jpg"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", filepath,
            "-ss", "00:00:05",      # Seek to 5 seconds in
            "-vframes", "1",        # Grab exactly one frame
            "-vf", "scale=320:-1",  # Resize to 320px wide
            thumb_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except FileNotFoundError:
        pass  # ffmpeg not installed — continue to online fallback
    except Exception:
        pass
    return None


async def get_online_thumbnail(url: str, download_dir: str) -> str | None:
    """
    Strategy 2: Fetch the Open Graph og:image from the source page.
    Works for most media sites (bbdownload, gdrive shares, etc.).
    Downloads the image and saves it locally as a JPEG thumbnail.
    Returns the local thumbnail path, or None on any failure.
    """
    import re

    thumb_path = os.path.join(download_dir, "_og_thumb.jpg")

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            # Step 1: Fetch the page HTML
            async with session.get(url, allow_redirects=True) as resp:
                if resp.content_type and "text" not in resp.content_type:
                    # It's a binary file directly — no HTML to scrape
                    return None
                html = await resp.text(errors="ignore")

            # Step 2: Extract og:image or twitter:image meta tags
            # Matches: <meta property="og:image" content="https://...">
            patterns = [
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
            ]
            img_url = None
            for pattern in patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    img_url = match.group(1).strip()
                    break

            if not img_url:
                return None

            # Make relative URLs absolute
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            elif img_url.startswith("/"):
                from urllib.parse import urlparse as _up
                base = _up(url)
                img_url = f"{base.scheme}://{base.netloc}{img_url}"

            # Step 3: Download the image
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


async def get_best_thumbnail(filepath: str, source_url: str, download_dir: str) -> str | None:
    """
    Get the best available thumbnail for a file+URL combo.
    Priority: ffmpeg (local video frame) → og:image (online) → None
    """
    # 1. Try local ffmpeg
    thumb = await get_thumbnail(filepath)
    if thumb:
        return thumb

    # 2. Try online Open Graph image from the source page
    thumb = await get_online_thumbnail(source_url, download_dir)
    if thumb:
        return thumb

    return None


# ---------------------------------------------------------------------------
# Page title extractor — returns a clean title from the source URL's HTML
# ---------------------------------------------------------------------------

async def get_page_title(url: str) -> str | None:
    """
    Fetch the <title> or og:title from the source URL's HTML.
    Used to set a human-readable name in the Telegram caption.
    Returns None on failure.
    """
    import re

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.content_type and "text" not in resp.content_type:
                    return None
                html = await resp.text(errors="ignore")

        # Try og:title first (cleaner), then fallback to <title>
        og = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
        if og:
            return og.group(1).strip()

        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if title_match:
            return title_match.group(1).strip()

    except Exception:
        pass

    return None
