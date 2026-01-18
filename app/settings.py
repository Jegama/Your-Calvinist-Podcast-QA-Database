"""
Application settings and configuration.
Loads environment variables and provides typed config objects.
"""

import os
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    # YouTube API
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    
    # Gemini API for classification
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # Playlist configuration
    PLAYLIST_ID: str = os.getenv("PLAYLIST_ID", "PLczriqVOY-tll3hzb2O7jHwKaEV1kd2IJ")
    
    # API Security
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "")
    CRON_SECRET: str = os.getenv("CRON_SECRET", "")
    
    # Processing configuration
    ANSWER_PREVIEW_LENGTH: int = 500  # Characters for answer preview
    
    def validate(self) -> list[str]:
        """Check for missing required settings. Returns list of missing keys."""
        missing = []
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL")
        if not self.GOOGLE_API_KEY:
            missing.append("GOOGLE_API_KEY")
        return missing


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
