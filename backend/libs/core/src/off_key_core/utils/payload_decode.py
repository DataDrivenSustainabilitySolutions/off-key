"""Bounded scalar decoding, including RFC 6901 extraction from JSON payloads."""

import json
import math

from off_key_core.schemas.system import SystemStream

MAX_PAYLOAD_BYTES = 65536
MAX_TEXT_LENGTH = 512
_UNSET = object()


def _pointer(value, pointer: str):
    for segment in pointer.split("/")[1:]:
        segment = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[segment]
        elif isinstance(value, list) and (
            segment == "0"
            or (
                segment.isascii()
                and segment.isdecimal()
                and not segment.startswith("0")
            )
        ):
            value = value[int(segment)]
        else:
            raise ValueError("JSON Pointer does not resolve to a scalar")
    return value


class PayloadDecoder:
    """Decode UTF-8 and JSON once even when many streams share one topic."""

    def __init__(self, payload: bytes):
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise ValueError("Payload exceeds the observation limit")
        self.text = payload.decode("utf-8")
        self.json_value = _UNSET

    def value(self, stream: SystemStream) -> float | bool | str:
        if (
            stream.payload_pointer is None
            and stream.value_type in {"text", "identifier"}
            and not self.text.startswith('"')
        ):
            return _scalar(self.text, stream.value_type)
        if self.json_value is _UNSET:
            self.json_value = json.loads(self.text)
        try:
            value = (
                _pointer(self.json_value, stream.payload_pointer)
                if stream.payload_pointer is not None
                else self.json_value
            )
        except (KeyError, IndexError, TypeError, RecursionError) as exc:
            raise ValueError("JSON Pointer cannot be resolved") from exc
        return _scalar(value, stream.value_type)


def _scalar(value, value_type: str) -> float | bool | str:
    if value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Expected a number")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Expected a finite number")
    elif value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Expected a boolean")
    elif (
        not isinstance(value, str)
        or len(value) > MAX_TEXT_LENGTH
        or len(value.encode("utf-8")) > MAX_TEXT_LENGTH * 4
        or "\x00" in value
    ):
        raise ValueError("Expected bounded text")
    return value


def decode_value(payload: bytes, stream: SystemStream) -> float | bool | str:
    return PayloadDecoder(payload).value(stream)
