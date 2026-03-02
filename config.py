import os
from pydantic_settings import BaseSettings
from pydantic import Field

# Render / Heroku may inject empty strings for undefined env vars.
# We sanitize them manually so Pydantic doesn't crash on int-parsing "".
_KEYS = ["API_ID", "API_HASH", "BOT_TOKEN", "PORT", "DOWNLOAD_DIR"]
for _k in _KEYS:
    if _k in os.environ and not os.environ[_k].strip():
        os.environ.pop(_k, None)


class Settings(BaseSettings):
    API_ID: int = Field(default=0)
    API_HASH: str = Field(default="")
    BOT_TOKEN: str = Field(default="")
    DOWNLOAD_DIR: str = Field(default="./downloads")
    # 1.9 GB in bytes — safe margin below Telegram Bot API's 2 GB per-file limit
    SPLIT_SIZE: int = Field(default=1900 * 1024 * 1024)
    PORT: int = Field(default=8080)


settings = Settings()
os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
