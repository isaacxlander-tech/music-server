"""Configuration settings for the music server"""
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    
    # Paths
    BASE_DIR: Path = Path(__file__).parent.parent
    MUSIC_DIR: Path = BASE_DIR / "music"
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    CONFIG_DIR: Path = BASE_DIR / "config"
    
    # Database
    DATABASE_URL: str = "sqlite:///./database/music.db"
    
    # Audio settings
    AUDIO_FORMAT: str = "flac"
    AUDIO_QUALITY: str = "best"
    
    # Plex structure settings
    PLEX_STRUCTURE: bool = True
    INCLUDE_YEAR_IN_ALBUM: bool = True
    
    # Download settings
    MAX_CONCURRENT_DOWNLOADS: int = 3
    DOWNLOAD_TIMEOUT: int = 600  # 10 minutes
    
    # API settings
    API_TITLE: str = "Music Server API"
    API_VERSION: str = "1.0.0"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    
    # Plex API settings
    PLEX_SERVER_URL: Optional[str] = None  # "http://127.0.0.1:32400"
    PLEX_TOKEN: Optional[str] = None
    PLEX_LIBRARY_SECTION_ID: Optional[int] = None
    PLEX_AUTO_SCAN: bool = False
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()

# Ensure directories exist
settings.MUSIC_DIR.mkdir(exist_ok=True)
settings.DOWNLOADS_DIR.mkdir(exist_ok=True)
settings.CONFIG_DIR.mkdir(exist_ok=True)
(settings.BASE_DIR / "database").mkdir(exist_ok=True)

