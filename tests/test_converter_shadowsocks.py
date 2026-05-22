from __future__ import annotations

import base64
from urllib.parse import quote

from core.converters.protocols.shadowsocks import build_ss_url, parse_ss_url


def b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def test_shadowsocks_sip002_round_trip_preserves_key_fields() -> None:
    node = {
        "name": "中文节点",
        "type": "ss",
        "server": "example.com",
        "port": 8388,
        "cipher": "aes-256-gcm",
        "password": "p@ss word",
        "udp": True,
        "tfo": False,
        "group": "默认组",
        "plugin-info": "v2ray-plugin;mode=websocket",
    }

    url = build_ss_url(node)
    assert url is not None
    parsed = parse_ss_url(url)

    assert parsed is not None
    assert parsed["name"] == "中文节点"
    assert parsed["type"] == "ss"
    assert parsed["server"] == "example.com"
    assert parsed["port"] == 8388
    assert parsed["cipher"] == "aes-256-gcm"
    assert parsed["password"] == "p@ss word"
    assert parsed["udp"] is True
    assert parsed["tfo"] is False
    assert parsed["group"] == "默认组"
    assert parsed["plugin-info"] == "v2ray-plugin;mode=websocket"


def test_shadowsocks_parses_plain_userinfo() -> None:
    parsed = parse_ss_url("ss://aes-128-gcm:password@example.com:443#Plain")

    assert parsed is not None
    assert parsed["cipher"] == "aes-128-gcm"
    assert parsed["password"] == "password"
    assert parsed["server"] == "example.com"
    assert parsed["port"] == 443
    assert parsed["name"] == "Plain"


def test_shadowsocks_parses_legacy_whole_base64() -> None:
    encoded = b64("chacha20-ietf-poly1305:secret@example.org:9000")

    parsed = parse_ss_url(f"ss://{encoded}#Legacy")

    assert parsed is not None
    assert parsed["cipher"] == "chacha20-ietf-poly1305"
    assert parsed["password"] == "secret"
    assert parsed["server"] == "example.org"
    assert parsed["port"] == 9000


def test_shadowsocks_decodes_url_encoded_name() -> None:
    parsed = parse_ss_url(f"ss://{b64('aes-256-gcm:pw')}@example.com:443#{quote('香港 01')}")

    assert parsed is not None
    assert parsed["name"] == "香港 01"


def test_shadowsocks_rejects_invalid_prefix() -> None:
    assert parse_ss_url("trojan://password@example.com:443#name") is None


def test_shadowsocks_rejects_invalid_port() -> None:
    assert parse_ss_url(f"ss://{b64('aes-256-gcm:pw')}@example.com:not-a-port#name") is None


def test_shadowsocks_build_rejects_missing_required_fields() -> None:
    assert build_ss_url({"name": "broken", "server": "example.com", "port": 443}) is None
