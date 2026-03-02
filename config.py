import os
from pydantic_settings import BaseSettings
from pydantic import Field

# Clean up empty strings from environment (Render may inject these) to prevent Pydantic V2 crashes
for key in ["API_ID", "API_HASH", "BOT_TOKEN", "PORT", "DOWNLOAD_DIR"]:
    if key in os.environ and not os.environ[key].strip():
        del os.environ[key]

class Settings(BaseSettings):
    API_ID: int = Field(default=0)
    API_HASH: str = Field(default="")
    BOT_TOKEN: str = Field(default="")
    DOWNLOAD_DIR: str = Field(default="./downloads")
    # 1.9 GB in bytes — safe margin below Telegram's 2 GB bot limit
    SPLIT_SIZE: int = Field(default=1900 * 1024 * 1024)
    PORT: int = Field(default=8080)

settings = Settings()
os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
