"""VLESS protocol URL parsing and building."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from core.models import ProxyNode


VLESS_PREFIX = "vless://"
DEFAULT_PARSE_NAME = "未命名 VLESS 节点"
DEFAULT_BUILD_NAME = "未命名节点"
DEFAULT_PORT = 443


def parse_vless_url(vless_url: str) -> ProxyNode | None:
    try:
        if not vless_url.startswith(VLESS_PREFIX):
            return None
        parsed = urlparse(vless_url)
        query = parse_qs(parsed.query)
        node: ProxyNode = {
            "name": unquote(parsed.fragment) if parsed.fragment else DEFAULT_PARSE_NAME,
            "type": "vless",
            "server": parsed.hostname,
            "port": int(parsed.port) if parsed.port else DEFAULT_PORT,
            "uuid": parsed.username or "",
            "udp": True,
            "tls": first_query_value(query, "security") in ("tls", "reality", "xtls"),
            "network": first_query_value(query, "type", "tcp"),
            "skip-cert-verify": first_query_value(query, "allowInsecure", "0") == "1",
        }
        apply_parse_options(node, query)
        return node
    except (ValueError, KeyError, IndexError) as exc:
        print(f"解析 VLESS URL 失败: {exc}")
        return None


def build_vless_url(node: dict[str, Any]) -> str | None:
    try:
        server = node.get("server", "")
        port = node.get("port", DEFAULT_PORT)
        uuid = node.get("uuid", "")
        name = node.get("name", DEFAULT_BUILD_NAME)
        if not all([server, port, uuid]):
            print(f"节点 {name} 缺少必要字段")
            return None
        params = build_query_params(node)
        qs = "&".join(
            f"{key}={quote(str(value), safe='')}" for key, value in params.items() if value
        )
        return f"{VLESS_PREFIX}{uuid}@{server}:{port}?{qs}#{quote(str(name), safe='')}"
    except (TypeError, ValueError) as exc:
        print(f"构建 VLESS URL 失败: {exc}")
        return None


def first_query_value(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def apply_parse_options(node: ProxyNode, query: dict[str, list[str]]) -> None:
    sni = first_query_value(query, "sni") or first_query_value(query, "serverName")
    if sni:
        node["servername"] = sni
    flow = first_query_value(query, "flow")
    if flow:
        node["flow"] = flow
    if node["network"] == "ws":
        node["ws-opts"] = {
            "path": first_query_value(query, "path", "/"),
            "headers": {"Host": first_query_value(query, "host")},
        }
    elif node["network"] == "grpc":
        node["grpc-opts"] = {"grpc-service-name": first_query_value(query, "serviceName")}
    apply_reality_options(node, query)


def apply_reality_options(node: ProxyNode, query: dict[str, list[str]]) -> None:
    public_key = first_query_value(query, "pbk")
    if public_key:
        node["reality-opts"] = {
            "public-key": public_key,
            "short-id": first_query_value(query, "sid"),
        }


def build_query_params(node: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"type": node.get("network", "tcp")}
    if node.get("tls"):
        params["security"] = "tls"
    apply_reality_build_options(params, node)
    add_if_present(params, "sni", node.get("servername", ""))
    add_if_present(params, "flow", node.get("flow", ""))
    apply_transport_build_options(params, node)
    if node.get("skip-cert-verify"):
        params["allowInsecure"] = "1"
    return params


def apply_reality_build_options(params: dict[str, Any], node: dict[str, Any]) -> None:
    reality_opts = node.get("reality-opts")
    if not isinstance(reality_opts, dict):
        return
    params["security"] = "reality"
    params["pbk"] = reality_opts.get("public-key", "")
    add_if_present(params, "sid", reality_opts.get("short-id"))


def apply_transport_build_options(params: dict[str, Any], node: dict[str, Any]) -> None:
    network = node.get("network")
    if network == "ws":
        ws_opts = node.get("ws-opts", {})
        if not isinstance(ws_opts, dict):
            return
        params["path"] = ws_opts.get("path", "/")
        headers = ws_opts.get("headers", {})
        host = headers.get("Host", "") if isinstance(headers, dict) else ""
        add_if_present(params, "host", host)
    elif network == "grpc":
        grpc_opts = node.get("grpc-opts", {})
        service_name = grpc_opts.get("grpc-service-name", "") if isinstance(grpc_opts, dict) else ""
        params["serviceName"] = service_name


def add_if_present(params: dict[str, Any], key: str, value: Any) -> None:
    if value:
        params[key] = value


__all__ = ["build_vless_url", "parse_vless_url"]
