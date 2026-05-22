from __future__ import annotations

from core.converters.protocols.shadowsocksr import build_ssr_url, parse_ssr_url


def test_shadowsocksr_round_trip_preserves_key_fields() -> None:
    node = {
        "name": "中文节点",
        "type": "ssr",
        "server": "example.com",
        "port": 8388,
        "password": "secret",
        "cipher": "aes-256-cfb",
        "protocol": "auth_sha1_v4",
        "protocol-param": "proto-param",
        "obfs": "tls1.2_ticket_auth",
        "obfs-param": "obfs.example.com",
        "group": "默认组",
    }

    url = build_ssr_url(node)
    assert url is not None
    parsed = parse_ssr_url(url)

    assert parsed is not None
    assert parsed["name"] == "中文节点"
    assert parsed["type"] == "ssr"
    assert parsed["server"] == "example.com"
    assert parsed["port"] == 8388
    assert parsed["password"] == "secret"
    assert parsed["cipher"] == "aes-256-cfb"
    assert parsed["protocol"] == "auth_sha1_v4"
    assert parsed["protocol-param"] == "proto-param"
    assert parsed["obfs"] == "tls1.2_ticket_auth"
    assert parsed["obfs-param"] == "obfs.example.com"
    assert parsed["group"] == "默认组"
    assert parsed["udp"] is True


def test_shadowsocksr_defaults_optional_fields() -> None:
    url = build_ssr_url(
        {
            "server": "example.org",
            "port": 9000,
            "password": "pw",
        }
    )

    assert url is not None
    parsed = parse_ssr_url(url)
    assert parsed is not None
    assert parsed["name"] == "未命名 SSR 节点"
    assert parsed["group"] == "ShadowsocksR"
    assert parsed["cipher"] == "aes-256-cfb"
    assert parsed["protocol"] == "origin"
    assert parsed["obfs"] == "plain"


def test_shadowsocksr_rejects_invalid_prefix() -> None:
    assert parse_ssr_url("ss://abc") is None


def test_shadowsocksr_rejects_invalid_payload() -> None:
    assert parse_ssr_url("ssr://not-valid") is None


def test_shadowsocksr_rejects_missing_main_fields() -> None:
    assert parse_ssr_url("ssr://c2VydmVyOjQ0Mw==") is None
