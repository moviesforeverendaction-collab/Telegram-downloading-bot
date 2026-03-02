import aiohttp
import asyncio
import time
from typing import Optional, Callable

RPC_URL = "http://localhost:6800/jsonrpc"


class Aria2Error(Exception):
    """Custom exception for Aria2 errors."""
    pass


async def aria2_rpc(method: str, params: list = None) -> Optional[dict]:
    """
    Send a JSON-RPC request to the aria2c daemon.
    
    Args:
        method: RPC method name
        params: RPC parameters
    
    Returns:
        Result dict or None on error
    """
    if params is None:
        params = []
    
    payload = {
        "jsonrpc": "2.0",
        "id": f"{method}_{int(time.time() * 1000)}",
        "method": method,
        "params": params
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(RPC_URL, json=payload) as response:
                if response.status != 200:
                    print(f"[aria2] HTTP Error {response.status}")
                    return None
                
                result = await response.json()
                
                if "error" in result:
                    error_msg = result["error"].get("message", "Unknown error")
                    print(f"[aria2] RPC Error: {error_msg}")
                    return None
                
                return result.get("result")
    
    except aiohttp.ClientError as e:
        print(f"[aria2] Connection error: {e}")
        return None
    except Exception as e:
        print(f"[aria2] Unexpected error: {e}")
        return None


async def add_download(uri: str, download_dir: str, options: dict = None) -> Optional[str]:
    """
    Add a URI (HTTP/HTTPS/FTP/Magnet) or Torrent to aria2c.
    
    Args:
        uri: Download URI or magnet link
        download_dir: Directory to save files
        options: Additional aria2 options
    
    Returns:
        GID (download ID) or None on error
    """
    default_options = {
        "dir": download_dir,
        "max-connection-per-server": "16",
        "split": "16",
        "min-split-size": "1M",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "seed-time": "0",  # Don't seed torrents
    }
    
    if options:
        default_options.update(options)
    
    # Direct HTTP/HTTPS/FTP link or magnet
    if uri.startswith(("http://", "https://", "ftp://", "magnet:")):
        gid = await aria2_rpc("aria2.addUri", [[uri], default_options])
        return gid
    
    return None


async def add_torrent(torrent_path: str, download_dir: str, options: dict = None) -> Optional[str]:
    """
    Add a torrent file to aria2c.
    
    Args:
        torrent_path: Path to .torrent file
        download_dir: Directory to save files
        options: Additional aria2 options
    
    Returns:
        GID or None on error
    """
    import base64
    
    try:
        with open(torrent_path, 'rb') as f:
            torrent_data = base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        print(f"[aria2] Error reading torrent file: {e}")
        return None
    
    default_options = {
        "dir": download_dir,
        "seed-time": "0",
    }
    
    if options:
        default_options.update(options)
    
    gid = await aria2_rpc("aria2.addTorrent", [torrent_data, [], default_options])
    return gid


async def get_download_status(gid: str) -> Optional[dict]:
    """
    Get the current status of a download by GID.
    
    Args:
        gid: Download GID
    
    Returns:
        Status dict or None on error
    """
    keys = [
        "status", "totalLength", "completedLength", "downloadSpeed",
        "uploadSpeed", "connections", "errorCode", "errorMessage",
        "followedBy", "following", "belongsTo", "dir", "files",
        "infoHash", "numSeeders", "seeder"
    ]
    
    return await aria2_rpc("aria2.tellStatus", [gid, keys])


async def remove_download(gid: str) -> bool:
    """
    Remove a download by GID.
    
    Args:
        gid: Download GID
    
    Returns:
        True if successful
    """
    result = await aria2_rpc("aria2.remove", [gid])
    return result is not None


async def pause_download(gid: str) -> bool:
    """
    Pause a download.
    
    Args:
        gid: Download GID
    
    Returns:
        True if successful
    """
    result = await aria2_rpc("aria2.pause", [gid])
    return result is not None


async def unpause_download(gid: str) -> bool:
    """
    Unpause a download.
    
    Args:
        gid: Download GID
    
    Returns:
        True if successful
    """
    result = await aria2_rpc("aria2.unpause", [gid])
    return result is not None


async def get_global_stats() -> Optional[dict]:
    """Get global aria2 statistics."""
    keys = ["downloadSpeed", "uploadSpeed", "numActive", "numWaiting", "numStopped"]
    return await aria2_rpc("aria2.getGlobalStat", [keys])


async def monitor_download(
    gid: str,
    progress_callback: Callable,
    start_time: float,
    action: str = "Downloading"
) -> tuple:
    """
    Monitor an aria2 download until it completes or errors out.
    
    Args:
        gid: Download GID
        progress_callback: Async callback(action, current, total, start_time, speed, eta)
        start_time: Download start timestamp
        action: Action name for progress display
    
    Returns:
        Tuple of (success: bool, result: str)
        result is filepath on success, error message on failure
    """
    current_gid = gid
    last_update_time = time.time()
    update_interval = 3.0
    
    while True:
        try:
            status_info = await get_download_status(current_gid)
            
            if not status_info:
                await asyncio.sleep(2)
                continue
            
            status = status_info.get("status")
            total_len = int(status_info.get("totalLength", 0))
            completed_len = int(status_info.get("completedLength", 0))
            speed = int(status_info.get("downloadSpeed", 0))
            
            # Handle metadata download completion (torrents)
            if status == "complete":
                followed_by = status_info.get("followedBy")
                if followed_by and isinstance(followed_by, list) and len(followed_by) > 0:
                    print(f"[aria2] Metadata done, following to: {followed_by[0]}")
                    current_gid = followed_by[0]
                    continue
                
                # Find the actual downloaded file path
                files = status_info.get("files", [])
                downloaded_file = None
                
                if files and len(files) > 0:
                    # Get the first file's path
                    downloaded_file = files[0].get("path", "")
                    # Handle torrent directories
                    if downloaded_file and os.path.isdir(downloaded_file):
                        # Find first file in directory
                        try:
                            for f in sorted(os.listdir(downloaded_file)):
                                file_path = os.path.join(downloaded_file, f)
                                if os.path.isfile(file_path):
                                    downloaded_file = file_path
                                    break
                        except Exception as e:
                            print(f"[aria2] Error listing directory: {e}")
                
                if downloaded_file and os.path.exists(downloaded_file):
                    return True, downloaded_file
                else:
                    return False, "Download completed but file path not found"
            
            elif status == "error":
                err_msg = status_info.get("errorMessage", "Unknown error")
                err_code = status_info.get("errorCode", "?")
                return False, f"Error {err_code}: {err_msg}"
            
            elif status == "removed":
                return False, "Download was removed"
            
            elif status in ("active", "waiting", "paused"):
                now = time.time()
                
                # Progress callback
                if progress_callback and (now - last_update_time >= update_interval):
                    if speed > 0 and total_len > completed_len:
                        remaining_bytes = total_len - completed_len
                        eta_seconds = remaining_bytes / speed
                    else:
                        eta_seconds = 0
                    
                    await progress_callback(
                        action,
                        completed_len,
                        total_len,
                        start_time,
                        speed=speed,
                        eta_seconds=eta_seconds
                    )
                    last_update_time = now
            
            await asyncio.sleep(2)
            
        except Exception as e:
            print(f"[aria2] Monitor error: {e}")
            await asyncio.sleep(2)


# Import os at module level for the monitor function
import os
