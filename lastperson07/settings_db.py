import json
import os
import threading
from typing import Optional
from config import settings

DB_FILE = os.path.join(settings.DOWNLOAD_DIR, "user_settings.json")
_db_lock = threading.Lock()

# In-memory cache
_user_settings = {}
_db_loaded = False


def load_db():
    """Load settings from disk."""
    global _user_settings, _db_loaded
    
    with _db_lock:
        if _db_loaded:
            return
        
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        _user_settings = json.loads(content)
                    else:
                        _user_settings = {}
                print(f"[settings_db] Loaded settings for {len(_user_settings)} users")
            except json.JSONDecodeError as e:
                print(f"[settings_db] Error parsing {DB_FILE}: {e}")
                _user_settings = {}
            except Exception as e:
                print(f"[settings_db] Error loading {DB_FILE}: {e}")
                _user_settings = {}
        else:
            _user_settings = {}
        
        _db_loaded = True


def save_db():
    """Save settings to disk."""
    with _db_lock:
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(DB_FILE) or ".", exist_ok=True)
            
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(_user_settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[settings_db] Error saving {DB_FILE}: {e}")


def get_user_setting(user_id: int, key: str, default=None):
    """Get a setting value for a user."""
    load_db()
    user_id_str = str(user_id)
    
    with _db_lock:
        if user_id_str in _user_settings:
            return _user_settings[user_id_str].get(key, default)
        return default


def set_user_setting(user_id: int, key: str, value):
    """Set a setting value for a user."""
    load_db()
    user_id_str = str(user_id)
    
    with _db_lock:
        if user_id_str not in _user_settings:
            _user_settings[user_id_str] = {}
        _user_settings[user_id_str][key] = value
    
    save_db()


def delete_user_setting(user_id: int, key: str):
    """Delete a setting for a user."""
    load_db()
    user_id_str = str(user_id)
    
    with _db_lock:
        if user_id_str in _user_settings and key in _user_settings[user_id_str]:
            del _user_settings[user_id_str][key]
    
    save_db()


def get_all_user_settings(user_id: int) -> dict:
    """Get all settings for a user."""
    load_db()
    user_id_str = str(user_id)
    
    with _db_lock:
        return _user_settings.get(user_id_str, {}).copy()


# ---------------------------------------------------------------------------
# Specific setting helpers
# ---------------------------------------------------------------------------

def get_dump_channel(user_id: int) -> Optional[int]:
    """Get the dump channel ID for a user."""
    return get_user_setting(user_id, "dump_channel")


def set_dump_channel(user_id: int, channel_id: int):
    """Set the dump channel ID for a user."""
    set_user_setting(user_id, "dump_channel", channel_id)


def get_custom_caption(user_id: int) -> Optional[str]:
    """Get the custom caption for a user."""
    return get_user_setting(user_id, "custom_caption")


def set_custom_caption(user_id: int, caption: str):
    """Set the custom caption for a user."""
    set_user_setting(user_id, "custom_caption", caption)


def get_custom_thumb(user_id: int) -> Optional[str]:
    """Get the custom thumbnail file_id for a user."""
    return get_user_setting(user_id, "custom_thumb")


def set_custom_thumb(user_id: int, thumb_file_id: str):
    """Set the custom thumbnail file_id for a user."""
    set_user_setting(user_id, "custom_thumb", thumb_file_id)


# Load on module import
load_db()
