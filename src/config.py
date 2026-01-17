from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # LLM Configuration
    LLM_API_KEY: str
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o"
    LLM_TEMPERATURE: float = 0.7

    # Language Settings
    TRANSCRIPT_LANG: str = "auto"
    OUTPUT_LANG: str = "zh"

    # System Settings
    LOG_LEVEL: str = "INFO"
    MAX_RETRIES: int = 3
    MAX_CONCURRENCY: int = 5
    
    # Paths
    OUTPUT_DIR: str = "outputs"
    CACHE_DIR: str = ".cache"
    COOKIES_PATH: Optional[str] = None
    
    # Raw Cookies from Env
    BILIBILI_COOKIES: Optional[str] = None
    YOUTUBE_COOKIES: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
