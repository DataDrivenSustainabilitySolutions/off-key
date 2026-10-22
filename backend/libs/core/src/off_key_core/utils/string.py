
from ..config.logs import logger


def string_to_float(value_str):
    """Safely converts a string to float."""
    try:
        return float(value_str)
    except (ValueError, TypeError):
        logger.debug(f"Could not convert '{value_str}' to float, returning None.")
        return None
