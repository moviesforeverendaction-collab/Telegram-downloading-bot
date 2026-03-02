import os
from config import settings


def cleanup(filepath: str):
    """Safely remove a file and all its split parts."""
    if not filepath:
        return
        
    # Remove the main file
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception as e:
            print("Cleanup error for main file: {}".format(e))
    
    # Remove any split parts
    base, ext = os.path.splitext(filepath)
    part_num = 1
    while True:
        part_path = "{}.part{:03d}{}".format(base, part_num, ext)
        if not os.path.exists(part_path):
            break
        try:
            os.remove(part_path)
        except Exception as e:
            print("Cleanup error for part {}: {}".format(part_num, e))
        part_num += 1


def cleanup_all_by_base(base_filepath: str):
    """Remove file and all associated thumbnails and parts."""
    if not base_filepath:
        return
        
    # Get the directory
    download_dir = os.path.dirname(base_filepath) or settings.DOWNLOAD_DIR
    
    # Clean up main file and parts
    cleanup(base_filepath)
    
    # Clean up thumbnails
    base_name = os.path.splitext(os.path.basename(base_filepath))[0]
    for f in os.listdir(download_dir):
        if f.startswith(("_poster_", "_og_thumb_", base_name)) and f.endswith((".jpg", ".thumb.jpg")):
            try:
                os.remove(os.path.join(download_dir, f))
            except Exception:
                pass
