import os
from typing import Optional
from dotenv import load_dotenv

from logger import get_logger

log = get_logger("CONFIG")

# Load environment variables
load_dotenv()

class Config:
    """Centralized configuration for Veyra."""
    
    # Required parameters
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    APPLICATION_ID: str = os.getenv("APPLICATION_ID", "")
    FOUNDER_ID_STR: str = os.getenv("FOUNDER_ID", "")
    
    # Optional / Future parameters
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production").lower()
    
    @classmethod
    def get_founder_id(cls) -> Optional[int]:
        try:
            return int(cls.FOUNDER_ID_STR) if cls.FOUNDER_ID_STR else None
        except ValueError:
            return None

    @classmethod
    def validate(cls) -> bool:
        """Validates that all required configuration is present."""
        missing = []
        if not cls.DISCORD_TOKEN:
            missing.append("DISCORD_TOKEN")
        if not cls.APPLICATION_ID:
            missing.append("APPLICATION_ID")
        if not cls.FOUNDER_ID_STR:
            missing.append("FOUNDER_ID")
        elif cls.get_founder_id() is None:
            log.error("FOUNDER_ID is not a valid integer.")
            return False
            
        if missing:
            log.error(f"Missing required configuration variables: {', '.join(missing)}")
            return False
            
        return True

config = Config()
