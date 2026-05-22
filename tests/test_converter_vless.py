from __future__ import annotations

from core.converters.protocols.vless import build_vless_url, parse_vless_url


UUID = "00000000-0000-0000-0000-000000000000"


def test_vless_ws_round_trip_preserves_key_fields() -> None:
    node = {
        "name": "中文节点",
        "type": "vless",
        "server": "example.com",
        "port": 443,
        "uuid": UUID,
        "tls": True,
        "network": "ws",
        "servername": "sni.example.com",
        "flow": "xtls-rprx-vision",
        "skip-cert-verify": True,
        "ws-opts": {"path": "/ws", "headers": {"Host": "cdn.example.com"}},
    }

    url = build_vless_url(node)
    assert url is not None
    parsed = parse_vless_url(url)

    assert parsed is not None
    assert parsed["name"] == "中文节点"
    assert parsed["type"] == "vless"
    assert parsed["server"] == "example.com"
    assert parsed["port"] == 443
    assert parsed["uuid"] == UUID
    assert parsed["tls"] is True
    assert parsed["network"] == "ws"
    assert parsed["servername"] == "sni.example.com"
    assert parsed["flow"] == "xtls-rprx-vision"
    assert parsed["skip-cert-verify"] is True
    assert parsed["ws-opts"]["path"] == "/ws"
    assert parsed["ws-opts"]["headers"]["Host"] == "cdn.example.com"


def test_vless_grpc_round_trip_preserves_service_name() -> None:
    url = build_vless_url(
        {
            "name": "grpc-node",
            "type": "vless",
            "server": "grpc.example.com",
            "port": 8443,
            "uuid": UUID,
            "network": "grpc",
            "grpc-opts": {"grpc-service-name": "svc"},
        }
    )

    assert url is not None
    parsed = parse_vless_url(url)
    assert parsed is not None
    assert parsed["network"] == "grpc"
    assert parsed["grpc-opts"]["grpc-service-name"] == "svc"


def test_vless_reality_round_trip_preserves_reality_options() -> None:
    url = build_vless_url(
        {
            "name": "reality-node",
            "type": "vless",
            "server": "reality.example.com",
            "port": 443,
            "uuid": UUID,
            "reality-opts": {"public-key": "pubkey", "short-id": "abcd"},
        }
    )

    assert url is not None
    parsed = parse_vless_url(url)
    assert parsed is not None
    assert parsed["tls"] is True
    assert parsed["reality-opts"]["public-key"] == "pubkey"
    assert parsed["reality-opts"]["short-id"] == "abcd"


def test_vless_rejects_invalid_prefix() -> None:
    assert parse_vless_url("trojan://password@example.com:443#name") is None


def test_vless_rejects_invalid_port() -> None:
    assert parse_vless_url(f"vless://{UUID}@example.com:not-a-port#name") is None


def test_vless_build_rejects_missing_required_fields() -> None:
    assert build_vless_url({"name": "broken", "server": "example.com", "port": 443}) is None
