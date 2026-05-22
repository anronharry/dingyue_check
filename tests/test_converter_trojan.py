from __future__ import annotations

from core.converters.protocols.trojan import build_trojan_url, parse_trojan_url


def test_trojan_round_trip_preserves_key_fields() -> None:
    node = {
        "name": "中文节点",
        "type": "trojan",
        "server": "example.com",
        "port": 443,
        "password": "p@ss word",
        "sni": "sni.example.com",
        "skip-cert-verify": True,
    }

    url = build_trojan_url(node)
    assert url is not None
    parsed = parse_trojan_url(url)

    assert parsed is not None
    assert parsed["name"] == "中文节点"
    assert parsed["type"] == "trojan"
    assert parsed["server"] == "example.com"
    assert parsed["port"] == 443
    assert parsed["password"] == "p%40ss%20word"
    assert parsed["sni"] == "sni.example.com"
    assert parsed["skip-cert-verify"] is True


def test_trojan_rejects_invalid_prefix() -> None:
    assert parse_trojan_url("vmess://abc") is None


def test_trojan_rejects_invalid_port() -> None:
    assert parse_trojan_url("trojan://password@example.com:not-a-port#name") is None


def test_trojan_build_rejects_missing_required_fields() -> None:
    assert build_trojan_url({"name": "broken", "server": "example.com", "port": 443}) is None


def test_trojan_parse_defaults_port_and_name() -> None:
    parsed = parse_trojan_url("trojan://password@example.com")

    assert parsed is not None
    assert parsed["name"] == "未命名 Trojan 节点"
    assert parsed["port"] == 443
    assert parsed["sni"] == "example.com"
