"""ShadowsocksR protocol URL parsing and building."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from core.models import ProxyNode


SSR_PREFIX = "ssr://"
DEFAULT_NODE_NAME = "未命名 SSR 节点"
DEFAULT_GROUP = "ShadowsocksR"
BASE64_PADDING_MOD = 4


def parse_ssr_url(ssr_url: str) -> ProxyNode | None:
    try:
        if not ssr_url.startswith(SSR_PREFIX):
            return None
        decoded = decode_ssr_base64(ssr_url[len(SSR_PREFIX) :].strip())
        main_part, params = split_ssr_payload(decoded)
        fields = main_part.split(":")
        if len(fields) < 6:
            return None
        return build_node(fields, params)
    except (ValueError, IndexError, TypeError, binascii.Error) as exc:
        print(f"解析 SSR URL 失败: {exc}")
        return None


def build_ssr_url(node: dict[str, Any]) -> str | None:
    try:
        password_b64 = encode_ssr_base64(node.get("password", ""))
        main_part = build_main_part(node, password_b64)
        params = build_params(node)
        full_text = f"{main_part}/?{'&'.join(params)}"
        final_b64 = base64.b64encode(full_text.encode("utf-8")).decode("utf-8")
        return f"{SSR_PREFIX}{final_b64}"
    except (TypeError, ValueError) as exc:
        print(f"构建 SSR URL 失败: {exc}")
        return None


def decode_ssr_base64(data: str) -> str:
    normalized = data.replace("-", "+").replace("_", "/")
    return base64.b64decode(pad_base64(normalized)).decode("utf-8", errors="ignore")


def encode_ssr_base64(data: Any) -> str:
    if not data:
        return ""
    return base64.b64encode(str(data).encode("utf-8")).decode("utf-8")


def pad_base64(value: str) -> str:
    padding = len(value) % BASE64_PADDING_MOD
    return value + "=" * (BASE64_PADDING_MOD - padding) if padding else value


def split_ssr_payload(decoded: str) -> tuple[str, dict[str, str]]:
    main_part, param_part = decoded.split("/?", 1) if "/?" in decoded else (decoded, "")
    params: dict[str, str] = {}
    if param_part:
        for item in param_part.split("&"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            params[key] = decode_ssr_base64(value)
    return main_part, params


def build_node(fields: list[str], params: dict[str, str]) -> ProxyNode:
    return {
        "name": params.get("remarks", DEFAULT_NODE_NAME),
        "type": "ssr",
        "server": fields[0],
        "port": int(fields[1]),
        "password": decode_ssr_base64(fields[5]),
        "cipher": fields[3],
        "protocol": fields[2],
        "protocol-param": params.get("protoparam", ""),
        "obfs": fields[4],
        "obfs-param": params.get("obfsparam", ""),
        "group": params.get("group", DEFAULT_GROUP),
        "udp": True,
    }


def build_main_part(node: dict[str, Any], password_b64: str) -> str:
    server = node.get("server", "")
    port = str(node.get("port", 0))
    protocol = node.get("protocol", "origin")
    method = node.get("cipher", "aes-256-cfb")
    obfs = node.get("obfs", "plain")
    return f"{server}:{port}:{protocol}:{method}:{obfs}:{password_b64}"


def build_params(node: dict[str, Any]) -> list[str]:
    params: list[str] = []
    append_encoded_param(params, "obfsparam", node.get("obfs-param"))
    append_encoded_param(params, "protoparam", node.get("protocol-param"))
    append_encoded_param(params, "remarks", node.get("name"))
    append_encoded_param(params, "group", node.get("group"))
    return params


def append_encoded_param(params: list[str], key: str, value: Any) -> None:
    if value:
        params.append(f"{key}={encode_ssr_base64(value)}")


__all__ = ["build_ssr_url", "parse_ssr_url"]
