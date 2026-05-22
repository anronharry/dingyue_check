"""YAML import and export helpers for SSNodeConverter."""

from __future__ import annotations

import os
from typing import Any

import yaml  # type: ignore[import-untyped]


def to_yaml(
    *,
    output_file: str,
    nodes: list[dict[str, Any]],
    remarks: str = "",
    status: str = "",
    full_config: bool = True,
) -> bool:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        yaml_data = build_yaml_data(nodes, remarks, status, full_config)
        with open(output_file, "w", encoding="utf-8") as handle:
            yaml.dump(
                yaml_data, handle, allow_unicode=True, default_flow_style=False, sort_keys=False
            )
        print(f"成功导出到yaml文件: {output_file}")
        return True
    except OSError as exc:
        print(f"导出yaml文件失败(文件系统错误): {exc}")
        return False
    except yaml.YAMLError as exc:
        print(f"导出yaml文件失败(YAML序列化错误): {exc}")
        return False


def parse_yaml_file(file_path: str) -> tuple[bool, list[dict[str, Any]], str, str]:
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            yaml_data = yaml.safe_load(handle)
        if not isinstance(yaml_data, dict):
            print("yaml 文件为空或格式不合法（顶层不是字典）")
            return False, [], "", ""
        if "proxies" not in yaml_data:
            print("yaml 文件中未找到 proxies 字段")
            return False, [], "", ""
        nodes = yaml_data["proxies"] or []
        metadata = (
            yaml_data.get("metadata", {}) if isinstance(yaml_data.get("metadata"), dict) else {}
        )
        remarks = metadata.get("remarks", "")
        status = metadata.get("status", "")
        print(f"成功解析 {len(nodes)} 个节点")
        return len(nodes) > 0, nodes, remarks, status
    except OSError as exc:
        print(f"读取 yaml 文件失败(文件系统错误): {exc}")
        return False, [], "", ""
    except yaml.YAMLError as exc:
        print(f"读取 yaml 文件失败(YAML反序列化错误): {exc}")
        return False, [], "", ""


def build_yaml_data(
    nodes: list[dict[str, Any]], remarks: str, status: str, full_config: bool
) -> dict[str, Any]:
    if not full_config:
        yaml_data: dict[str, Any] = {"proxies": nodes}
        metadata = build_metadata(remarks, status)
        if metadata:
            yaml_data["metadata"] = metadata
        return yaml_data
    return build_full_config(nodes)


def build_metadata(remarks: str, status: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if remarks:
        metadata["remarks"] = remarks
    if status:
        metadata["status"] = status
    return metadata


def build_full_config(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    proxy_names = [node["name"] for node in nodes]
    return {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "external-controller": "127.0.0.1:9090",
        "proxies": nodes,
        "proxy-groups": build_proxy_groups(proxy_names),
        "rules": build_rules(),
    }


def build_proxy_groups(proxy_names: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "name": "🚀 节点选择",
            "type": "select",
            "proxies": ["⚡ 自动选择", "🎯 全球直连"] + proxy_names,
        },
        {
            "name": "⚡ 自动选择",
            "type": "url-test",
            "url": "http://www.gstatic.com/generate_204",
            "interval": 300,
            "proxies": proxy_names,
        },
        {
            "name": "🎬 视频流媒体",
            "type": "select",
            "proxies": ["🚀 节点选择", "⚡ 自动选择"] + proxy_names,
        },
        {
            "name": "📲 社交工具",
            "type": "select",
            "proxies": ["🚀 节点选择", "🎯 全球直连"] + proxy_names,
        },
        {"name": "🍎 苹果服务", "type": "select", "proxies": ["🎯 全球直连", "🚀 节点选择"]},
        {"name": "🛑 广告拦截", "type": "select", "proxies": ["REJECT", "DIRECT"]},
        {"name": "🎯 全球直连", "type": "select", "proxies": ["DIRECT", "REJECT"]},
    ]


def build_rules() -> list[str]:
    return [
        "DOMAIN-SUFFIX,google.com,🚀 节点选择",
        "DOMAIN-KEYWORD,youtube,🎬 视频流媒体",
        "DOMAIN-KEYWORD,netflix,🎬 视频流媒体",
        "DOMAIN-KEYWORD,telegram,📲 社交工具",
        "DOMAIN-SUFFIX,apple.com,🍎 苹果服务",
        "DOMAIN-SUFFIX,icloud.com,🍎 苹果服务",
        "MATCH,🚀 节点选择",
    ]


__all__ = ["parse_yaml_file", "to_yaml"]
