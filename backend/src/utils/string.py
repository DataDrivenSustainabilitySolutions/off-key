from typing import Optional
from urllib.parse import unquote


def clean_string(input_string: str) -> str:
    decoded_str = unquote(input_string)  # Decode URL encoding
    return decoded_str.replace("/", "")  # Remove slashes


def string_to_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except ValueError:
        return None
