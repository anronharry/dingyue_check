"""Vmess protocol URL parsing and building."""

from __future__ import annotations

import binascii
import json
from typing import Any

from core.converters.serialization import decode_base64_json, encode_base64_json
from core.models import ProxyNode


VMESS_PREFIX = "vmess://"
DEFAULT_NODE_NAME = "未命名节点"


def parse_vmess_url(vmess_url: str) -> ProxyNode | None:
    try:
        if not vmess_url.startswith(VMESS_PREFIX):
            return None
        config = decode_base64_json(vmess_url[len(VMESS_PREFIX) :])
        return build_node_from_config(config)
    except (json.JSONDecodeError, ValueError, KeyError, binascii.Error) as exc:
        print(f"解析 Vmess URL 失败: {exc}")
        return None


def build_vmess_url(node: dict[str, Any]) -> str | None:
    try:
        config = build_config_from_node(node)
        return f"{VMESS_PREFIX}{encode_base64_json(config)}"
    except (TypeError, ValueError) as exc:
        print(f"构建 Vmess URL 失败: {exc}")
        return None


def build_node_from_config(config: dict[str, Any]) -> ProxyNode:
    node: ProxyNode = {
        "name": str(config.get("ps", DEFAULT_NODE_NAME)),
        "type": "vmess",
        "server": config.get("add"),
        "port": int(config.get("port", 0)),
        "uuid": config.get("id"),
        "alterId": int(config.get("aid", 0)),
        "cipher": config.get("type", "auto"),
        "udp": True,
        "tls": config.get("tls") == "tls" or config.get("tls") is True,
    }
    apply_transport_options(node, config)
    apply_server_name(node, config)
    return node


def apply_transport_options(node: ProxyNode, config: dict[str, Any]) -> None:
    net = config.get("net")
    if net == "ws":
        node["network"] = "ws"
        node["ws-opts"] = {
            "path": config.get("path", "/"),
            "headers": {"Host": config.get("host", "")},
        }
    elif net == "h2":
        node["network"] = "h2"
        node["h2-opts"] = {
            "path": config.get("path", "/"),
            "host": [config.get("host", "")],
        }


def apply_server_name(node: ProxyNode, config: dict[str, Any]) -> None:
    if config.get("sni"):
        node["servername"] = config.get("sni")
    elif config.get("host") and node["tls"]:
        node["servername"] = config.get("host")


def build_config_from_node(node: dict[str, Any]) -> dict[str, Any]:
    port = require_vmess_port(node)
    require_vmess_text(node, "server")
    require_vmess_text(node, "uuid")
    ws_opts = node.get("ws-opts", {})
    h2_opts = node.get("h2-opts", {})
    net = node.get("network", "tcp")
    config = {
        "v": "2",
        "ps": node.get("name", DEFAULT_NODE_NAME),
        "add": node.get("server", ""),
        "port": str(port),
        "id": node.get("uuid", ""),
        "aid": str(node.get("alterId", 0)),
        "scy": node.get("cipher", "auto"),
        "net": net,
        "type": "none",
        "host": "",
        "path": "",
        "tls": "tls" if node.get("tls") else "",
        "sni": node.get("servername", ""),
        "alpn": "",
    }
    apply_config_transport(config, net, ws_opts, h2_opts)
    return config


def require_vmess_text(node: dict[str, Any], field: str) -> str:
    value = str(node.get(field, "") or "").strip()
    if not value:
        raise ValueError(f"missing required vmess field: {field}")
    return value


def require_vmess_port(node: dict[str, Any]) -> int:
    try:
        port = int(node.get("port", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid vmess port") from exc
    if port <= 0:
        raise ValueError("missing required vmess field: port")
    return port


def apply_config_transport(config: dict[str, Any], net: str, ws_opts: Any, h2_opts: Any) -> None:
    if net == "ws" and isinstance(ws_opts, dict):
        config["path"] = ws_opts.get("path", "/")
        headers = ws_opts.get("headers", {})
        config["host"] = headers.get("Host", "") if isinstance(headers, dict) else ""
    elif net == "h2" and isinstance(h2_opts, dict):
        config["path"] = h2_opts.get("path", "/")
        hosts = h2_opts.get("host", [])
        config["host"] = hosts[0] if hosts else ""


__all__ = ["build_vmess_url", "parse_vmess_url"]
