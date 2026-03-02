"""
lastperson07 - Supporting modules for TG Leecher Bot.

This package contains:
- aria2_client: RPC client for Aria2 download manager
- settings_db: JSON-based user settings storage
- split_utils: File splitting utilities for large files
"""

__version__ = "1.0.0"

from .aria2_client import (
    aria2_rpc,
    add_download,
    add_torrent,
    get_download_status,
    monitor_download,
    remove_download,
    pause_download,
    unpause_download,
    get_global_stats,
    Aria2Error,
)

from .settings_db import (
    get_user_setting,
    set_user_setting,
    get_dump_channel,
    set_dump_channel,
    get_custom_caption,
    set_custom_caption,
    get_custom_thumb,
    set_custom_thumb,
)

from .split_utils import split_large_file

__all__ = [
    # Aria2
    'aria2_rpc',
    'add_download',
    'add_torrent',
    'get_download_status',
    'monitor_download',
    'remove_download',
    'pause_download',
    'unpause_download',
    'get_global_stats',
    'Aria2Error',
    # Settings
    'get_user_setting',
    'set_user_setting',
    'get_dump_channel',
    'set_dump_channel',
    'get_custom_caption',
    'set_custom_caption',
    'get_custom_thumb',
    'set_custom_thumb',
    # Split
    'split_large_file',
]
