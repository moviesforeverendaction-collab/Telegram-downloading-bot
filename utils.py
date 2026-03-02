import aiohttp
import os
import time
from urllib.parse import urlparse
from config import settings

def format_bytes(size: int) -> str:
    power = 2**10
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{round(size, 2)}{power_labels.get(n, '')}B"

def format_progress_bar(current: int, total: int) -> str:
    percentage = current * 100 / total if total else 0
    filled = int(percentage / 10)
    bar = '▓' * filled + '░' * (10 - filled)
    return f"[{bar}] {round(percentage, 2)}%"

async def download_file(url: str, progress_callback=None):
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename:
        filename = "downloaded_file"
    
    filepath = os.path.join(settings.DOWNLOAD_DIR, filename)
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            content_length = response.headers.get('content-length')
            total_size = int(content_length) if content_length else 0
            downloaded = 0
            
            with open(filepath, 'wb') as f:
                start_time = time.time()
                last_update = start_time
                async for chunk in response.content.iter_chunked(1024 * 1024): # 1MB chunks
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    now = time.time()
                    # Only callback every 2 seconds to avoid Telegram rate limits
                    if progress_callback and (now - last_update > 2.0 or downloaded == total_size):
                        await progress_callback("Downloading", downloaded, total_size, start_time)
                        last_update = now
                        
    return filepath
