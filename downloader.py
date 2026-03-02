import aiohttp
import os
import time
from urllib.parse import urlparse
from config import settings

# Browser-like headers to avoid blocks
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


async def resolve_url(url: str) -> tuple:
    """Resolve URL and extract filename."""
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        async with session.get(url, allow_redirects=True) as response:
            response.raise_for_status()
            
            final_url = str(response.url)
            
            # Try to get filename from Content-Disposition header
            cd = response.headers.get("Content-Disposition", "")
            filename = ""
            
            if "filename=" in cd:
                parts = cd.split("filename=")
                if len(parts) > 1:
                    filename = parts[-1].strip().strip('"\'').split(";")[0].strip()
            
            # Fallback to URL path
            if not filename:
                parsed = urlparse(final_url)
                path = parsed.path
                if path:
                    filename = os.path.basename(path)
            
            # Last resort - guess from content type
            if not filename or "." not in filename:
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                ext = content_type.split("/")[-1].split(";")[0]
                if ext in ("octet-stream", "binary", "x-download"):
                    ext = "bin"
                filename = "downloaded_file.{}".format(ext)
            
            # Clean filename
            bad_chars = '\\/|:*?"<> '
            filename = "".join(c for c in filename if c not in bad_chars)
            if not filename:
                filename = "downloaded_file"
            
            return final_url, filename, response.headers


async def download_file(url: str, progress_callback=None):
    """
    Download file with progress tracking and unique filenames.
    
    Args:
        url: URL to download
        progress_callback: async function(status, current, total)
    
    Returns:
        Path to downloaded file
    """
    # Resolve URL and get filename
    final_url, filename, headers = await resolve_url(url)
    
    # Ensure unique filename
    base, ext = os.path.splitext(filename)
    filepath = os.path.join(settings.DOWNLOAD_DIR, filename)
    counter = 1
    while os.path.exists(filepath):
        filename = "{}_{}{}".format(base, counter, ext)
        filepath = os.path.join(settings.DOWNLOAD_DIR, filename)
        counter += 1
    
    # Get file size
    total_size = int(headers.get("Content-Length", 0))
    
    # Download with progress
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)
    
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        async with session.get(final_url) as response:
            response.raise_for_status()
            
            # Update total size if available
            if not total_size:
                total_size = int(response.headers.get("Content-Length", 0))
            
            downloaded = 0
            start_time = time.time()
            last_update = start_time
            
            with open(filepath, 'wb') as f:
                async for chunk in response.content.iter_chunked(1024 * 1024):  # 1MB chunks
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Update progress every 0.5 seconds
                    now = time.time()
                    if progress_callback and (now - last_update >= 0.5):
                        await progress_callback("downloading", downloaded, total_size)
                        last_update = now
            
            # Final progress update
            if progress_callback:
                await progress_callback("downloading", downloaded, downloaded)
    
    return filepath
