import os
from pydantic_settings import BaseSettings
from pydantic import Field

# Render/Heroku sometimes leaves empty strings for undefined environment variables.
# Pydantic V2 crashes trying to parse "" as an integer. We clean them up first.
for key in ["API_ID", "API_HASH", "BOT_TOKEN", "PORT", "DOWNLOAD_DIR"]:
    if key in os.environ and not os.environ[key].strip():
        del os.environ[key]

class Settings(BaseSettings):
    API_ID: int = Field(default=0)
    API_HASH: str = Field(default="")
    BOT_TOKEN: str = Field(default="")
    DOWNLOAD_DIR: str = Field(default="./downloads")
    PORT: int = Field(default=8080) # Required for Render

settings = Settings()
os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
