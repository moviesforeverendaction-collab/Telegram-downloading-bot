import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    API_ID: int = int(os.environ.get("API_ID", "0"))
    API_HASH: str = os.environ.get("API_HASH", "")
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
    DOWNLOAD_DIR: str = "./downloads"
    PORT: int = int(os.environ.get("PORT", "8080")) # Required for Render

settings = Settings()
os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
