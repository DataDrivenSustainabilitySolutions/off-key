"""Configuration module for off-key-core."""

from .config import Settings

# Create singleton settings instance
settings = Settings()

__all__ = ["Settings", "settings"]