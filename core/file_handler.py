"""File parsing helpers for TXT/YAML node lists and subscription links."""
from __future__ import annotations

import base64
import logging
import re
from typing import Dict, List
from urllib.parse import unquote, urlparse

import yaml

from core.converters.ss_converter import SSNodeConverter

logger = logging.getLogger(__name__)

TESTABLE_TEXT_PROTOCOLS = {"hysteria", "hysteria2", "tuic"}


class FileHandler:
    """File parsing helpers."""

    @staticmethod
    def extract_subscription_urls(content: bytes) -> List[str]:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("gbk", errors="ignore")

        urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', text)
        subscription_urls = []
        for url in urls:
            if any(ext in url.lower() for ext in [".jpg", ".png", ".gif", ".mp4", ".pdf"]):
                continue
            subscription_urls.append(url)
        return subscription_urls

    @staticmethod
    def parse_txt_file(content: bytes) -> List[Dict]:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("gbk", errors="ignore")

        if FileHandler._is_base64(text):
            try:
                text = base64.b64decode(text).decode("utf-8")
            except Exception:
                pass

        converter = SSNodeConverter()
        nodes = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            parsed_node = None
            if line.startswith("vmess://"):
                parsed_node = converter.parse_vmess_url(line)
            elif line.startswith("vless://"):
                parsed_node = converter.parse_vless_url(line)
            elif line.startswith("ss://"):
                parsed_node = converter.parse_ss_url(line)
            elif line.startswith("ssr://"):
                parsed_node = converter.parse_ssr_url(line)
            elif line.startswith("trojan://"):
                parsed_node = converter.parse_trojan_url(line)
            elif any(line.startswith(f"{protocol}://") for protocol in TESTABLE_TEXT_PROTOCOLS):
                parsed_node = FileHandler._parse_minimal_text_proxy(line)

            if not parsed_node:
                continue

            parsed_node["protocol"] = parsed_node.get("protocol") or parsed_node.get("type", "unknown")
            parsed_node["raw"] = line
            parsed_node["name"] = parsed_node.get("name") or FileHandler._extract_node_name(line)
            nodes.append(parsed_node)

        return nodes

    @staticmethod
    def _parse_minimal_text_proxy(line: str) -> Dict | None:
        parsed = urlparse(line)
        protocol = parsed.scheme.lower()
        if protocol not in TESTABLE_TEXT_PROTOCOLS:
            return None

        server = parsed.hostname or ""
        port = parsed.port or 0
        if not server or not port:
            # Fallback for links with uncommon authority formatting.
            host_part = parsed.netloc.rsplit("@", 1)[-1]
            if host_part.startswith("[") and "]" in host_part:
                host_end = host_part.find("]")
                server = server or host_part[1:host_end]
                port_part = host_part[host_end + 1 :].lstrip(":")
                if port_part.isdigit():
                    port = port or int(port_part)
            elif ":" in host_part:
                candidate_server, candidate_port = host_part.rsplit(":", 1)
                if candidate_port.isdigit():
                    server = server or candidate_server
                    port = port or int(candidate_port)

        if not server or not port:
            logger.debug("Skip untestable %s node because server/port is missing: %s", protocol, line)
            return {
                "protocol": protocol,
                "name": FileHandler._extract_node_name(line),
                "raw": line,
            }

        return {
            "protocol": protocol,
            "name": FileHandler._extract_node_name(line, fallback=server),
            "server": server,
            "port": int(port),
            "raw": line,
        }

    @staticmethod
    def parse_yaml_file(content: bytes) -> List[Dict]:
        try:
            text = content.decode("utf-8")
            config = yaml.safe_load(text)

            nodes = []
            if config and "proxies" in config:
                for proxy in config["proxies"]:
                    if isinstance(proxy, dict):
                        node = dict(proxy)
                        node["name"] = proxy.get("name", "未命名节点")
                        node["protocol"] = proxy.get("type", "unknown").lower()
                        node["server"] = proxy.get("server", "")
                        node["port"] = proxy.get("port", 0)
                        nodes.append(node)
            return nodes
        except Exception as exc:
            logger.error("YAML 解析失败: %s", exc)
            return []

    @staticmethod
    def convert_to_yaml(nodes: List[Dict]) -> str:
        config = {"proxies": []}
        for node in nodes:
            config["proxies"].append(
                {
                    "name": node.get("name", "未命名节点"),
                    "type": node.get("protocol", "ss"),
                    "server": node.get("server", "unknown"),
                    "port": node.get("port", 0),
                }
            )
        return yaml.dump(config, allow_unicode=True, default_flow_style=False)

    @staticmethod
    def _is_base64(text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        clean_text = text.replace("\n", "").replace("\r", "")
        if not clean_text:
            return False
        base64_pattern = r"^[A-Za-z0-9+/]*={0,2}$"
        return len(clean_text) % 4 == 0 and bool(re.match(base64_pattern, clean_text))

    @staticmethod
    def _extract_node_name(line: str, *, fallback: str = "未命名节点") -> str:
        if "#" in line:
            name = line.split("#", 1)[1]
            try:
                name = unquote(name)
            except Exception:
                pass
            name = name.strip()
            if name:
                return name
        return fallback
