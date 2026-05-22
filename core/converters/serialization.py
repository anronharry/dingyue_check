"""Shared URL serialization helpers for proxy converters."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any


BASE64_PADDING_MOD = 4


def pad_base64(value: str) -> str:
    padding = len(value) % BASE64_PADDING_MOD
    if not padding:
        return value
    return value + "=" * (BASE64_PADDING_MOD - padding)


def decode_base64_json(value: str) -> dict[str, Any]:
    decoded = base64.b64decode(pad_base64(value)).decode("utf-8")
    config = json.loads(decoded)
    if not isinstance(config, dict):
        raise ValueError("base64 JSON payload is not an object")
    return config


def encode_base64_json(value: dict[str, Any]) -> str:
    json_text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(json_text.encode("utf-8")).decode("utf-8").rstrip("=")


__all__ = [
    "binascii",
    "decode_base64_json",
    "encode_base64_json",
    "pad_base64",
]
