import logging
import sys

# Create a logger instance
logger = logging.getLogger("app")
logger.setLevel(logging.INFO)  # Change to DEBUG if needed

# Create a stream handler (logs to stdout for Docker compatibility)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)

# Define log format
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
handler.setFormatter(formatter)

# Avoid duplicate handlers
if not logger.hasHandlers():
    logger.addHandler(handler)

__all__ = ["logger"]
