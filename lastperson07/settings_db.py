import json
import os
from config import settings

DB_FILE = os.path.join(settings.DOWNLOAD_DIR, "user_settings.json")

# In-memory cache
_user_settings = {}

def load_db():
    global _user_settings
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    _user_settings = json.loads(content)
                else:
                    _user_settings = {}
        except Exception as e:
            print(f"Error loading {DB_FILE}: {e}")
            _user_settings = {}
    else:
        _user_settings = {}

def save_db():
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(_user_settings, f, indent=4)
    except Exception as e:
        print(f"Error saving {DB_FILE}: {e}")

# Load on module import
os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
load_db()

def get_user_setting(user_id: int, key: str, default=None):
    user_id_str = str(user_id)
    if user_id_str in _user_settings:
        return _user_settings[user_id_str].get(key, default)
    return default

def set_user_setting(user_id: int, key: str, value):
    user_id_str = str(user_id)
    if user_id_str not in _user_settings:
        _user_settings[user_id_str] = {}
    _user_settings[user_id_str][key] = value
    save_db()

def get_dump_channel(user_id: int):
    return get_user_setting(user_id, "dump_channel")

def set_dump_channel(user_id: int, channel_id: int):
    set_user_setting(user_id, "dump_channel", channel_id)

def get_custom_caption(user_id: int):
    return get_user_setting(user_id, "custom_caption")

def set_custom_caption(user_id: int, caption: str):
    set_user_setting(user_id, "custom_caption", caption)

def get_custom_thumb(user_id: int):
    return get_user_setting(user_id, "custom_thumb")

def set_custom_thumb(user_id: int, thumb_file_id: str):
    set_user_setting(user_id, "custom_thumb", thumb_file_id)
