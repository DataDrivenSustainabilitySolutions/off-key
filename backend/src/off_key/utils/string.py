from urllib.parse import unquote

from ..core.logs import logger


def clean_string(input_string: str) -> None | str:
    """
    Decodes URL encoding and removes forward slashes from the input string.
    Example: 'Sensor%2FPower%2FCurrent' -> 'SensorPowerCurrent'
             'Sensor/Power/Current' -> 'SensorPowerCurrent'
    """
    if not isinstance(input_string, str):  # Basic type check
        logger.warning(
            f"clean_string received non-string input: {type(input_string)}. "
            f"Returning None."
        )
        return None
    decoded_str = unquote(
        input_string
    )  # Decode potential URL encoding (e.g., %2F -> /)
    return decoded_str.replace("/", "")  # Remove all forward slashes


def string_to_float(value_str):
    """Safely converts a string to float."""
    try:
        return float(value_str)
    except (ValueError, TypeError):
        logger.debug(f"Could not convert '{value_str}' to float, returning None.")
        return None
