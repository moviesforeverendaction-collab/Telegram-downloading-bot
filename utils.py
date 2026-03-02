import re
import os
import time
import json
import asyncio
import aiohttp
import datetime

from urllib.parse import urlparse, quote_plus
from config import settings

# ---------------------------------------------------------------------------
# Browser-like headers
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
}

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_bytes(size):
    size = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return "{:.2f} {}".format(size, unit)
        size /= 1024.0
    return "{:.2f} PB".format(size)


def format_speed(bps):
    return format_bytes(bps) + "/s"


def format_eta(seconds):
    if seconds <= 0 or seconds > 86400:
        return "∞"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return "{}h {}m {}s".format(h, m, s)
    if m:
        return "{}m {}s".format(m, s)
    return "{}s".format(s)


def format_duration(seconds):
    """Return readable duration: '2h 5m 33s'."""
    if not seconds or seconds <= 0:
        return "Unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return "{}h {}m {}s".format(h, m, s)
    if m:
        return "{}m {}s".format(m, s)
    return "{}s".format(s)


def format_progress(current, total, start_time, action):
    """Render progress bar string for Telegram (MarkdownV2-safe)."""
    elapsed = time.time() - start_time
    speed = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / speed if speed > 0 else 0
    pct = (current / total * 100.0) if total > 0 else 0.0
    filled = min(int(pct / 5), 20)
    bar = "█" * filled + "░" * (20 - filled)
    icon = "⬇️" if "Download" in action else "⬆️"
    return (
        "{} <b>{}</b>\n"
        "<code>{}</code> {:.1f}%\n"
        "📦 {} / {}\n"
        "⚡ {}  |  ⏱ ETA: {}"
    ).format(
        icon, action,
        bar, pct,
        format_bytes(current), format_bytes(total),
        format_speed(speed), format_eta(remaining)
    )


# ---------------------------------------------------------------------------
# URL resolver
# ---------------------------------------------------------------------------

async def resolve_final_url(url):
    timeout = aiohttp.ClientTimeout(total=60, connect=15)
    connector = aiohttp.TCPConnector(limit=16, ttl_dns_cache=300)
    async with aiohttp.ClientSession(
        headers=HEADERS, timeout=timeout, connector=connector
    ) as session:
        async with session.get(url, allow_redirects=True) as resp:
            resp.raise_for_status()
            final_url = str(resp.url)

            cd = resp.headers.get("Content-Disposition", "")
            filename = ""
            if "filename=" in cd:
                part = cd.split("filename=")[-1].strip().strip("\"'")
                filename = part.split(";")[0].strip()

            if not filename:
                path = urlparse(final_url).path
                name = os.path.basename(path)
                if name and "." in name:
                    filename = name

            if not filename or "." not in filename:
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
                ext = ctype.split(";")[0].split("/")[-1]
                if ext in ("octet-stream", "force-download", "x-download", "binary"):
                    ext = "bin"
                filename = "leech_file.{}".format(ext)

    return final_url, filename


# ---------------------------------------------------------------------------
# Downloader — 4 MB chunks for speed
# ---------------------------------------------------------------------------

async def download_file(url, progress_callback=None):
    final_url, filename = await resolve_final_url(url)

    bad_chars = set('\\/|:*?"<>')
    filename = "".join(c for c in filename if c not in bad_chars).strip()
    if not filename:
        filename = "leech_file"

    filepath = os.path.join(settings.DOWNLOAD_DIR, filename)
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=120)
    connector = aiohttp.TCPConnector(limit=16, ttl_dns_cache=300, force_close=False)

    async with aiohttp.ClientSession(
        headers=HEADERS, timeout=timeout, connector=connector
    ) as session:
        async with session.get(final_url, allow_redirects=True) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            start_time = time.time()
            last_update = start_time

            with open(filepath, "wb") as f:
                async for chunk in resp.content.iter_chunked(4 * 1024 * 1024):  # 4 MB
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
# Video metadata via ffprobe
# ---------------------------------------------------------------------------

async def extract_video_metadata(filepath):
    """
    Run ffprobe to extract duration, resolution, codecs, bitrate.
    Returns a dict. All values are None if ffprobe is unavailable or fails.
    """
    result = {
        "duration": None,   # int seconds
        "width": None,
        "height": None,
        "video_codec": None,
        "audio_codec": None,
        "bitrate_kbps": None,
    }
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            filepath,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if not stdout:
            return result

        data = json.loads(stdout.decode("utf-8", errors="ignore"))
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        # Duration
        dur = fmt.get("duration") or next(
            (s.get("duration") for s in streams if s.get("duration")), None
        )
        if dur:
            result["duration"] = int(float(dur))

        # Bitrate
        brate = fmt.get("bit_rate")
        if brate:
            result["bitrate_kbps"] = int(int(brate) / 1000)

        # Video stream
        for s in streams:
            if s.get("codec_type") == "video" and not result["video_codec"]:
                result["video_codec"] = s.get("codec_name", "").upper()
                result["width"] = s.get("width")
                result["height"] = s.get("height")

        # Audio stream
        for s in streams:
            if s.get("codec_type") == "audio" and not result["audio_codec"]:
                result["audio_codec"] = s.get("codec_name", "").upper()

    except (FileNotFoundError, OSError):
        pass  # ffprobe not installed
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Title cleaner — extracts movie/show name from a messy filename
# ---------------------------------------------------------------------------

# Tags that appear in scene/web-dl filenames after the actual title
_STOP_TAGS = re.compile(
    r"(\d{4})"                           # Year: 2023
    r"|(\b(?:4k|2160p|1080p|720p|480p|4320p|hd|fhd|uhd)\b)"
    r"|(\b(?:bluray|bdrip|brrip|web[\-\.]?dl|webrip|hdtv|dvdrip|hdcam|ts|camrip)\b)"
    r"|(\b(?:x264|x265|h264|h265|hevc|avc|xvid|divx|vp9|av1)\b)"
    r"|(\b(?:aac|ac3|dts|dd|eac3|atmos|truehd|flac|mp3|opus)\b)"
    r"|(\b(?:extended|directors\.cut|ultimate|remastered|proper|repack|retail)\b)"
    r"|(\b(?:yify|yts|sparks|fgt|mkvcage|qxr|psych|ion10)\b)",
    re.IGNORECASE,
)

def clean_title(filename):
    """
    Extract a clean title from a filename like:
    'Ant.Man.and.the.Wasp.2023.1080p.BluRay.x264.mkv'
    → 'Ant Man and the Wasp'
    """
    name, _ = os.path.splitext(filename)
    # Replace dots, underscores, hyphens with spaces
    name = re.sub(r"[._]", " ", name)
    # Strip leading/trailing spaces
    name = name.strip()

    # Find first stop tag position and cut there
    m = _STOP_TAGS.search(name)
    if m:
        name = name[:m.start()].strip()

    # Capitalise words
    name = " ".join(w.capitalize() for w in name.split())
    return name if name else filename


# ---------------------------------------------------------------------------
# Movie / Series poster fetching — iTunes API (free, no key)
# ---------------------------------------------------------------------------

async def fetch_movie_poster(title, download_dir):
    """
    Search iTunes for a movie/show poster using the given title.
    Downloads the best available artwork and saves it as a local JPEG.
    Returns local path or None.
    """
    poster_path = os.path.join(download_dir, "_poster.jpg")
    try:
        query = quote_plus(title)
        url = "https://itunes.apple.com/search?term={}&media=movie&limit=3&entity=movie".format(query)

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)

        results = data.get("results", [])
        if not results:
            # Try TV search fallback
            url2 = "https://itunes.apple.com/search?term={}&media=tvShow&limit=3".format(query)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url2) as resp:
                    if resp.status == 200:
                        data2 = await resp.json(content_type=None)
                        results = data2.get("results", [])

        if not results:
            return None

        # Get the highest-res artwork (replace 100x100bb with 600x600bb)
        artwork_url = results[0].get("artworkUrl100", "")
        if not artwork_url:
            return None
        artwork_url = artwork_url.replace("100x100bb", "600x600bb")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(artwork_url) as img_resp:
                if img_resp.status == 200:
                    data_bytes = await img_resp.read()
                    if data_bytes:
                        with open(poster_path, "wb") as f:
                            f.write(data_bytes)
                        return poster_path

    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Thumbnail engine
# ---------------------------------------------------------------------------

async def get_thumbnail_ffmpeg(filepath):
    """Extract a video frame at 5s using ffmpeg. Returns path or None."""
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
        pass
    except Exception:
        pass
    return None


async def get_thumbnail_online(source_url, download_dir):
    """Scrape og:image / twitter:image from source page. Returns path or None."""
    thumb_path = os.path.join(download_dir, "_og_thumb.jpg")
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(source_url, allow_redirects=True) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if "text" not in ctype:
                    return None
                html = await resp.text(errors="ignore")

        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        ]
        img_url = None
        for pattern in patterns:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                img_url = m.group(1).strip()
                break

        if not img_url:
            return None

        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("/"):
            parsed = urlparse(source_url)
            img_url = "{}://{}{}".format(parsed.scheme, parsed.netloc, img_url)

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


async def get_best_thumbnail(filepath, source_url, download_dir, title=None):
    """
    Priority: Movie poster (iTunes) → ffmpeg frame → og:image → None
    """
    # 1. Movie poster via iTunes (if we have a title)
    if title:
        poster = await fetch_movie_poster(title, download_dir)
        if poster:
            return poster

    # 2. ffmpeg frame (for videos)
    thumb = await get_thumbnail_ffmpeg(filepath)
    if thumb:
        return thumb

    # 3. OG image from source page
    thumb = await get_thumbnail_online(source_url, download_dir)
    return thumb  # May be None


# ---------------------------------------------------------------------------
# Page title extractor
# ---------------------------------------------------------------------------

async def get_page_title(url):
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if "text" not in ctype:
                    return None
                html = await resp.text(errors="ignore")

        m = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()

        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    except Exception:
        pass
    return None
