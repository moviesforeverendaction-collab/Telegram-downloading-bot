import aiohttp
import os
import time
from typing import Optional, Callable
from urllib.parse import urlparse

from config import settings
from utils import HEADERS, logger, get_unique_filename, clean_filename


class DownloadError(Exception):
    """Custom exception for download errors."""
    pass


class Downloader:
    """Async file downloader with progress tracking."""
    
    def __init__(self, chunk_size: int = 4 * 1024 * 1024):  # 4MB chunks
        self.chunk_size = chunk_size
        self._current_download = None
    
    async def resolve_url(self, url: str) -> tuple:
        """
        Resolve URL and extract filename.
        
        Returns:
            Tuple of (final_url, filename, headers)
        """
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        
        try:
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
                        filename = f"downloaded_file.{ext}"
                    
                    # Clean filename
                    filename = clean_filename(filename)
                    
                    return final_url, filename, response.headers
                    
        except aiohttp.ClientError as e:
            raise DownloadError(f"Failed to resolve URL: {e}")
        except Exception as e:
            raise DownloadError(f"Unexpected error resolving URL: {e}")
    
    async def download_file(
        self,
        url: str,
        progress_callback: Optional[Callable] = None,
        custom_filename: Optional[str] = None,
    ) -> str:
        """
        Download file with progress tracking.
        
        Args:
            url: URL to download
            progress_callback: async function(status, current, total)
            custom_filename: Optional custom filename override
        
        Returns:
            Path to downloaded file
        """
        # Resolve URL and get filename
        final_url, filename, headers = await self.resolve_url(url)
        
        if custom_filename:
            filename = clean_filename(custom_filename)
        
        # Ensure unique filename
        filepath = get_unique_filename(settings.DOWNLOAD_DIR, filename)
        
        # Get file size
        total_size = int(headers.get("Content-Length", 0))
        
        # Download with progress
        timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)
        
        try:
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
                        async for chunk in response.content.iter_chunked(self.chunk_size):
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
                    
                    logger.info(f"Downloaded: {filename} ({downloaded} bytes)")
                    return filepath
                    
        except aiohttp.ClientError as e:
            # Clean up partial download
            if os.path.exists(filepath):
                os.remove(filepath)
            raise DownloadError(f"Download failed: {e}")
        except Exception as e:
            # Clean up partial download
            if os.path.exists(filepath):
                os.remove(filepath)
            raise DownloadError(f"Unexpected error during download: {e}")
    
    async def download_with_retry(
        self,
        url: str,
        progress_callback: Optional[Callable] = None,
        custom_filename: Optional[str] = None,
        max_retries: int = 3,
    ) -> str:
        """
        Download file with retry logic.
        
        Args:
            url: URL to download
            progress_callback: Progress callback function
            custom_filename: Optional custom filename override
            max_retries: Maximum number of retry attempts
        
        Returns:
            Path to downloaded file
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return await self.download_file(url, progress_callback, custom_filename)
            except DownloadError as e:
                last_error = e
                logger.warning(f"Download attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
        
        raise last_error or DownloadError("All retry attempts failed")


# Legacy function for backward compatibility
async def download_file(url: str, progress_callback: Optional[Callable] = None) -> str:
    """Legacy download function for compatibility."""
    downloader = Downloader()
    return await downloader.download_file(url, progress_callback)


async def resolve_url(url: str) -> tuple:
    """Legacy resolve function for compatibility."""
    downloader = Downloader()
    return await downloader.resolve_url(url)


# Need to import asyncio for retry function
import asyncio
