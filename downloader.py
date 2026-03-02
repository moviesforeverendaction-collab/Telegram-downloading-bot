import aiohttp
import os
import time
from urllib.parse import urlparse
from config import settings

async def download_file(url: str, progress_callback=None):
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename:
        filename = "downloaded_file"
    
    filepath = os.path.join(settings.DOWNLOAD_DIR, filename)
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(filepath, 'wb') as f:
                async for chunk in response.content.iter_chunked(8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        await progress_callback("downloading", downloaded, total_size)
                        
    return filepath
