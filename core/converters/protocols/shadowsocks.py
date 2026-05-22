"""Shadowsocks protocol URL parsing and building."""

from __future__ import annotations

import base64
import binascii
from typing import Any
from urllib.parse import parse_qs, quote, unquote

from core.models import ProxyNode


SS_PREFIX = "ss://"
DEFAULT_NODE_NAME = "未命名节点"
BASE64_PADDING_MOD = 4


def parse_ss_url(ss_url: str) -> ProxyNode | None:
    try:
        if not ss_url.startswith(SS_PREFIX):
            return None
        body, node_name = split_name(ss_url[len(SS_PREFIX) :])
        body, query_params = split_query(body.strip())
        parsed = parse_ss_body(body.rstrip("/"))
        if parsed is None:
            return None
        server, port, method, password, plugin_info = parsed
        if not all([server, port, method, password]):
            return None
        node: ProxyNode = {
            "name": node_name,
            "type": "ss",
            "server": server,
            "port": port,
            "cipher": method,
            "password": password,
        }
        apply_query_options(node, query_params)
        if plugin_info:
            node["plugin-info"] = plugin_info
        return node
    except (ValueError, IndexError, binascii.Error):
        return None


def build_ss_url(node: dict[str, Any]) -> str | None:
    try:
        name = node.get("name", DEFAULT_NODE_NAME)
        server = node.get("server", "")
        port = node.get("port", 0)
        cipher = node.get("cipher", "")
        password = node.get("password", "")
        if not all([server, port, cipher, password]):
            print(f"节点 {name} 缺少必要字段")
            return None
        encoded = encode_userinfo(cipher, password, node.get("plugin-info", ""))
        ss_url = f"{SS_PREFIX}{encoded}@{server}:{port}/"
        query = build_query(node)
        if query:
            ss_url += "?" + "&".join(query)
        return ss_url + "#" + quote(str(name), safe="")
    except (TypeError, ValueError) as exc:
        print(f"构建SS URL失败: {exc}")
        return None


def split_name(body: str) -> tuple[str, str]:
    if "#" not in body:
        return body, DEFAULT_NODE_NAME
    body_without_name, raw_name = body.split("#", 1)
    return body_without_name, unquote(raw_name).strip()


def split_query(body: str) -> tuple[str, dict[str, str]]:
    if "?" not in body:
        return body, {}
    body_without_query, query_string = body.split("?", 1)
    params = parse_qs(query_string)
    return body_without_query, {key: first_value(value) for key, value in params.items()}


def first_value(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return value


def parse_ss_body(body: str) -> tuple[str, int, str, str, str] | None:
    if "@" in body:
        return parse_sip002_or_plain_body(body)
    return parse_legacy_base64_body(body)


def parse_sip002_or_plain_body(body: str) -> tuple[str, int, str, str, str] | None:
    encoded_part, server_part = body.rsplit("@", 1)
    server, port = parse_server_port(server_part)
    decoded = try_decode_base64_text(encoded_part)
    if decoded and ":" in decoded:
        method, password, plugin_info = split_credentials(decoded, maxsplit=2)
        return server, port, method, password, plugin_info
    if ":" not in encoded_part:
        return None
    method, password, plugin_info = split_credentials(encoded_part, maxsplit=1)
    return server, port, method, password, plugin_info


def parse_legacy_base64_body(body: str) -> tuple[str, int, str, str, str] | None:
    decoded = base64.b64decode(pad_base64(body)).decode("utf-8")
    if "@" not in decoded:
        return None
    credentials, address = decoded.rsplit("@", 1)
    if ":" not in credentials:
        return None
    method, password = credentials.split(":", 1)
    server, port = parse_server_port(address)
    return server, port, method, password, ""


def parse_server_port(value: str) -> tuple[str, int]:
    if ":" not in value:
        raise ValueError("missing port")
    server, port_text = value.rsplit(":", 1)
    return server, int(port_text.rstrip("/").strip())


def split_credentials(value: str, *, maxsplit: int) -> tuple[str, str, str]:
    parts = value.split(":", maxsplit)
    method = parts[0]
    password = parts[1] if len(parts) > 1 else ""
    plugin_info = parts[2] if len(parts) > 2 else ""
    return method, password, plugin_info


def try_decode_base64_text(value: str) -> str | None:
    try:
        return base64.b64decode(pad_base64(value)).decode("utf-8")
    except binascii.Error:
        return None


def pad_base64(value: str) -> str:
    padding = len(value) % BASE64_PADDING_MOD
    return value + "=" * (BASE64_PADDING_MOD - padding) if padding else value


def apply_query_options(node: ProxyNode, query_params: dict[str, str]) -> None:
    if "udp" in query_params:
        node["udp"] = query_params["udp"] == "1"
    if "tfo" in query_params:
        node["tfo"] = query_params["tfo"] == "1"
    if "group" in query_params:
        apply_group(node, query_params["group"])


def apply_group(node: ProxyNode, encoded_group: str) -> None:
    try:
        node["group"] = base64.b64decode(encoded_group).decode("utf-8")
    except binascii.Error:
        pass


def encode_userinfo(cipher: Any, password: Any, plugin_info: Any) -> str:
    text = f"{cipher}:{password}:{plugin_info}" if plugin_info else f"{cipher}:{password}"
    return base64.b64encode(text.encode("utf-8")).decode("utf-8").rstrip("=")


def build_query(node: dict[str, Any]) -> list[str]:
    query_parts: list[str] = []
    if "udp" in node:
        query_parts.append(f"udp={'1' if node['udp'] else '0'}")
    if "tfo" in node:
        query_parts.append(f"tfo={'1' if node['tfo'] else '0'}")
    if "group" in node:
        group_encoded = base64.b64encode(str(node["group"]).encode("utf-8")).decode("utf-8")
        query_parts.append(f"group={group_encoded}")
    return query_parts


__all__ = ["build_ss_url", "parse_ss_url"]
