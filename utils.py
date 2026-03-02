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


# Empty replacement for lines 76-314
