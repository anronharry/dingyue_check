from __future__ import annotations

from core.converters.protocols.vmess import build_vmess_url, parse_vmess_url


UUID = "00000000-0000-0000-0000-000000000000"


def test_vmess_round_trip_preserves_key_fields() -> None:
    node = {
        "name": "中文节点",
        "type": "vmess",
        "server": "example.com",
        "port": 443,
        "uuid": UUID,
        "alterId": 0,
        "cipher": "auto",
        "tls": True,
        "network": "ws",
        "ws-opts": {"path": "/ws", "headers": {"Host": "cdn.example.com"}},
        "servername": "sni.example.com",
    }

    url = build_vmess_url(node)
    assert url is not None
    parsed = parse_vmess_url(url)

    assert parsed is not None
    assert parsed["name"] == "中文节点"
    assert parsed["type"] == "vmess"
    assert parsed["server"] == "example.com"
    assert parsed["port"] == 443
    assert parsed["uuid"] == UUID
    assert parsed["tls"] is True
    assert parsed["network"] == "ws"
    assert parsed["ws-opts"]["path"] == "/ws"


def test_vmess_rejects_invalid_prefix() -> None:
    assert parse_vmess_url("trojan://password@example.com:443#name") is None


def test_vmess_rejects_invalid_base64_payload() -> None:
    assert parse_vmess_url("vmess://not-valid-json") is None


def test_vmess_supports_h2_transport() -> None:
    url = build_vmess_url(
        {
            "name": "h2-node",
            "type": "vmess",
            "server": "h2.example.com",
            "port": 8443,
            "uuid": UUID,
            "network": "h2",
            "h2-opts": {"path": "/h2", "host": ["h2-host.example.com"]},
        }
    )

    assert url is not None
    parsed = parse_vmess_url(url)
    assert parsed is not None
    assert parsed["network"] == "h2"
    assert parsed["h2-opts"]["path"] == "/h2"
    assert parsed["h2-opts"]["host"] == ["h2-host.example.com"]


def test_vmess_build_rejects_missing_required_fields() -> None:
    assert build_vmess_url({"name": "broken", "server": "example.com", "port": 443}) is None
    assert build_vmess_url({"name": "broken", "server": "example.com", "uuid": UUID}) is None
    assert build_vmess_url({"name": "broken", "port": 443, "uuid": UUID}) is None
