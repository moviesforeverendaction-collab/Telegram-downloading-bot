import os
import asyncio
import subprocess
from config import settings

async def split_large_file(filepath: str, max_size_bytes: int = settings.SPLIT_SIZE) -> list[str]:
    """
    Splits a large file natively via Linux `split` to avoid Python I/O blocking.
    Returns a list of resulting file paths.
    """
    if not os.path.exists(filepath):
        return []

    file_size = os.path.getsize(filepath)
    if file_size <= max_size_bytes:
        return [filepath]

    parts = []
    base, ext = os.path.splitext(filepath)
    prefix = f"{base}.part"
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "split", 
            "-b", f"{max_size_bytes}", 
            "-d", 
            "-a", "3", 
            "--additional-suffix", ext,
            filepath,
            prefix,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        await proc.communicate()
        
        dir_name = os.path.dirname(filepath)
        for f in sorted(os.listdir(dir_name)):
            if f.startswith(os.path.basename(prefix)) and f.endswith(ext):
                part_path = os.path.join(dir_name, f)
                parts.append(part_path)
                
        return parts if parts else [filepath]

    except Exception as e:
        print(f"Error splitting file with 'split' command: {e}")
        return [filepath]
