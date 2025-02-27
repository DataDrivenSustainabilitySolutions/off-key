from urllib.parse import unquote


def clean_string(input_string: str) -> str:
    decoded_str = unquote(input_string)  # Decode URL encoding
    return decoded_str.replace("/", "")  # Remove slashes

def convert_string_to_number(input_string: str) -> float | None:
    if input_string is None:
        return None
    try:
        num = float(input_string)
        return int(num) if num.is_integer() else num
    except ValueError:
        return None
