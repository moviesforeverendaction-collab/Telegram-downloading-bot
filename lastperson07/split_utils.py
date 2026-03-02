import os
import asyncio
import subprocess
from typing import List
from config import settings


async def split_large_file(filepath: str, max_size_bytes: int = None) -> List[str]:
    """
    Splits a large file natively via Linux `split` to avoid Python I/O blocking.
    Returns a list of resulting file paths.
    
    Args:
        filepath: Path to the file to split
        max_size_bytes: Maximum size per part (defaults to settings.SPLIT_SIZE)
    
    Returns:
        List of file paths (single item if no splitting needed)
    """
    if max_size_bytes is None:
        max_size_bytes = settings.SPLIT_SIZE
    
    if not os.path.exists(filepath):
        print(f"[split] File not found: {filepath}")
        return []
    
    file_size = os.path.getsize(filepath)
    
    # No need to split
    if file_size <= max_size_bytes:
        return [filepath]
    
    parts = []
    base, ext = os.path.splitext(filepath)
    prefix = f"{base}.part"
    
    print(f"[split] Splitting {filepath} ({file_size} bytes) into {max_size_bytes} byte parts")
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "split",
            "-b", str(max_size_bytes),
            "-d",  # Use numeric suffixes
            "-a", "3",  # 3 digits for suffix
            "--additional-suffix", ext,
            filepath,
            prefix,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            print(f"[split] Error: {stderr.decode()}")
            return [filepath]
        
        # Collect all parts
        dir_name = os.path.dirname(filepath) or "."
        prefix_name = os.path.basename(prefix)
        
        for f in sorted(os.listdir(dir_name)):
            if f.startswith(prefix_name) and f.endswith(ext):
                part_path = os.path.join(dir_name, f)
                if part_path != filepath:  # Don't include original file
                    parts.append(part_path)
        
        if not parts:
            print("[split] No parts created, returning original file")
            return [filepath]
        
        print(f"[split] Created {len(parts)} parts")
        return parts
        
    except Exception as e:
        print(f"[split] Error splitting file: {e}")
        return [filepath]


def get_part_filename(original_filename: str, part_num: int, total_parts: int) -> str:
    """
    Generate a filename for a file part.
    
    Args:
        original_filename: Original filename
        part_num: Current part number (1-indexed)
        total_parts: Total number of parts
    
    Returns:
        New filename with part suffix
    """
    base, ext = os.path.splitext(original_filename)
    padding = len(str(total_parts))
    return f"{base}.part{part_num:0{padding}d}{ext}"
