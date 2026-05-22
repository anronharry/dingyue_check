"""Trojan protocol URL parsing and building."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from core.models import ProxyNode


TROJAN_PREFIX = "trojan://"
DEFAULT_NODE_NAME = "未命名 Trojan 节点"
DEFAULT_BUILD_NAME = "未命名节点"
DEFAULT_PORT = 443


def parse_trojan_url(trojan_url: str) -> ProxyNode | None:
    try:
        if not trojan_url.startswith(TROJAN_PREFIX):
            return None
        parsed = urlparse(trojan_url)
        query = parse_qs(parsed.query)
        return {
            "name": unquote(parsed.fragment) if parsed.fragment else DEFAULT_NODE_NAME,
            "type": "trojan",
            "server": parsed.hostname,
            "port": int(parsed.port) if parsed.port else DEFAULT_PORT,
            "password": parsed.username,
            "udp": True,
            "sni": query.get("sni", [parsed.hostname])[0],
            "skip-cert-verify": query.get("allowInsecure", ["0"])[0] == "1",
        }
    except (ValueError, KeyError, IndexError) as exc:
        print(f"解析 Trojan URL 失败: {exc}")
        return None


def build_trojan_url(node: dict[str, Any]) -> str | None:
    try:
        server = node.get("server", "")
        port = node.get("port", DEFAULT_PORT)
        password = node.get("password", "")
        name = node.get("name", DEFAULT_BUILD_NAME)
        sni = node.get("sni", server)
        insecure = "1" if node.get("skip-cert-verify") else "0"
        if not all([server, port, password]):
            print(f"节点 {name} 缺少必要字段")
            return None
        url = f"{TROJAN_PREFIX}{quote(str(password), safe='')}@{server}:{port}"
        params = f"sni={quote(str(sni))}&allowInsecure={insecure}"
        return f"{url}?{params}#{quote(str(name), safe='')}"
    except (TypeError, ValueError) as exc:
        print(f"构建 Trojan URL 失败: {exc}")
        return None


__all__ = ["build_trojan_url", "parse_trojan_url"]
