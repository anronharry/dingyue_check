"""Node extraction orchestration for subscription payloads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote

import base64
import yaml  # type: ignore[import-untyped]

from core.file_handler import FileHandler


MAX_NODES = 300
YAML_SCAN_LIMIT = 5000
YAML_TRUNCATE_BYTES = 300 * 1024
ContentFormat = Literal["yaml", "text"]
NormalizeText = Callable[[str], str]
ContainsProtocol = Callable[[str], bool]
DecodeBase64 = Callable[[str], str | None]


@dataclass(frozen=True)
class ParsedNodes:
    nodes: list[dict]
    content_format: ContentFormat
    normalized_nodes: list[dict]
    normalized_content: str
    parse_notes: list[str]

    def as_tuple(self) -> tuple[list[dict], ContentFormat, list[dict], str, list[str]]:
        return (
            self.nodes,
            self.content_format,
            self.normalized_nodes,
            self.normalized_content,
            self.parse_notes,
        )


def parse_nodes(
    content: str,
    *,
    normalize_text: NormalizeText,
    contains_protocol: ContainsProtocol,
    decode_base64: DecodeBase64,
    max_nodes: int = MAX_NODES,
) -> ParsedNodes:
    parse_notes: list[str] = []
    normalized_original = normalize_text(content)
    yaml_nodes = parse_yaml_nodes_preserve_fields(normalized_original, max_nodes=max_nodes)
    if yaml_nodes is not None:
        parse_notes.append("direct-yaml")
        return build_result(yaml_nodes, "yaml", normalized_original, parse_notes)
    if contains_protocol(normalized_original):
        parse_notes.append("direct-protocol")
        nodes = parse_text_nodes(normalized_original, max_nodes)
        return build_result(nodes, "text", normalized_original, parse_notes)
    decoded_content = decode_base64(normalized_original)
    if decoded_content:
        return parse_decoded_nodes(decoded_content, parse_notes, max_nodes)
    parse_notes.append("unrecognized-content")
    nodes = parse_text_nodes(normalized_original, max_nodes)
    return build_result(nodes, "text", normalized_original, parse_notes)


def parse_decoded_nodes(
    decoded_content: str, parse_notes: list[str], max_nodes: int
) -> ParsedNodes:
    parse_notes.append("base64-decoded")
    yaml_nodes = parse_yaml_nodes_preserve_fields(decoded_content, max_nodes=max_nodes)
    if yaml_nodes is not None:
        parse_notes.append("decoded-yaml")
        return build_result(yaml_nodes, "yaml", decoded_content, parse_notes)
    nodes = parse_text_nodes(decoded_content, max_nodes)
    return build_result(nodes, "text", decoded_content, parse_notes)


def build_result(
    nodes: list[dict], content_format: ContentFormat, content: str, notes: list[str]
) -> ParsedNodes:
    return ParsedNodes(nodes, content_format, list(nodes), content, notes)


def parse_text_nodes(content: str, max_nodes: int) -> list[dict]:
    return FileHandler.parse_txt_file(content.encode("utf-8"))[:max_nodes]


def has_yaml_nodes(content: str, *, max_nodes: int = 1) -> bool:
    return parse_yaml_nodes(content, max_nodes=max_nodes) is not None


def parse_yaml_nodes(content: str, *, max_nodes: int) -> list[dict] | None:
    proxies = load_yaml_proxies(content)
    if proxies is None:
        return None
    nodes: list[dict] = []
    for proxy in proxies:
        if len(nodes) >= max_nodes:
            break
        if isinstance(proxy, dict):
            nodes.append(
                {
                    "name": proxy.get("name", "未命名节点"),
                    "protocol": proxy.get("type", "unknown").lower(),
                    "server": proxy.get("server", ""),
                    "port": proxy.get("port", 0),
                }
            )
    return nodes


def parse_yaml_nodes_preserve_fields(content: str, *, max_nodes: int) -> list[dict] | None:
    proxies = load_yaml_proxies(content)
    if proxies is None:
        return None
    nodes: list[dict] = []
    for proxy in proxies:
        if len(nodes) >= max_nodes:
            break
        if not isinstance(proxy, dict):
            continue
        nodes.append(normalize_yaml_proxy(proxy))
    return nodes


def normalize_yaml_proxy(proxy: dict) -> dict:
    row = dict(proxy)
    ptype = str(row.get("type", row.get("protocol", "unknown")) or "unknown").lower()
    row["type"] = ptype
    row["protocol"] = ptype
    row["name"] = row.get("name", "unnamed")
    row["server"] = row.get("server", "")
    row["port"] = row.get("port", 0)
    return row


def load_yaml_proxies(content: str) -> list | None:
    if not looks_like_yaml_subscription(content):
        return None
    try:
        config = yaml.safe_load(truncate_yaml_content(content))
    except Exception:
        return None
    if not isinstance(config, dict) or "proxies" not in config:
        return None
    proxies = config["proxies"]
    return proxies if isinstance(proxies, list) else None


def looks_like_yaml_subscription(content: str) -> bool:
    head = content[:YAML_SCAN_LIMIT]
    return content.strip().startswith("#") or "proxies:" in head or "proxy-groups:" in head


def truncate_yaml_content(content: str) -> str:
    if len(content) <= YAML_TRUNCATE_BYTES:
        return content
    truncate_idx = content.rfind("\n", 0, YAML_TRUNCATE_BYTES)
    return content[: truncate_idx if truncate_idx != -1 else YAML_TRUNCATE_BYTES]


def parse_node_line(line: str) -> dict | None:
    for protocol in protocol_prefixes():
        if line.startswith(protocol):
            return {
                "protocol": protocol.replace("://", ""),
                "name": extract_node_name(line, protocol),
                "raw": line,
            }
    return None


def extract_node_name(line: str, protocol: str) -> str:
    if "#" in line:
        fragment_name = line.split("#", 1)[1]
        try:
            return unquote(fragment_name).strip()
        except Exception:
            return fragment_name.strip()
    if protocol == "vmess://":
        vmess_name = extract_vmess_name(line)
        if vmess_name:
            return vmess_name
    return "未命名节点"


def extract_vmess_name(line: str) -> str | None:
    import json

    try:
        encoded_text = line.replace("vmess://", "")
        if len(encoded_text) % 4:
            encoded_text += "=" * (4 - len(encoded_text) % 4)
        config = json.loads(base64.b64decode(encoded_text).decode("utf-8"))
    except Exception:
        return None
    name = config.get("ps") if isinstance(config, dict) else None
    return str(name) if name else None


def protocol_prefixes() -> tuple[str, ...]:
    return (
        "vmess://",
        "vless://",
        "ss://",
        "ssr://",
        "trojan://",
        "hysteria://",
        "hysteria2://",
        "hy2://",
        "tuic://",
        "wireguard://",
    )


__all__ = [
    "ParsedNodes",
    "extract_node_name",
    "has_yaml_nodes",
    "parse_node_line",
    "parse_nodes",
    "parse_yaml_nodes",
    "parse_yaml_nodes_preserve_fields",
]
