from __future__ import annotations

from core.converters.ss_converter import SSNodeConverter


def test_yaml_round_trip_preserves_hysteria2_and_tuic_fields(tmp_path) -> None:
    source = SSNodeConverter()
    source.nodes = [
        {
            "name": "HY2 节点",
            "type": "hysteria2",
            "server": "hy2.example.com",
            "port": 443,
            "password": "secret",
            "sni": "sni.example.com",
            "skip-cert-verify": True,
            "alpn": ["h3"],
            "obfs": "salamander",
            "obfs-password": "obfs-secret",
        },
        {
            "name": "TUIC 节点",
            "type": "tuic",
            "server": "tuic.example.com",
            "port": 8443,
            "uuid": "00000000-0000-0000-0000-000000000000",
            "password": "tuic-secret",
            "congestion-controller": "bbr",
            "udp-relay-mode": "native",
            "disable-sni": False,
        },
    ]
    source.remarks = "roundtrip"
    source.status = "ok"
    output_file = tmp_path / "nodes.yaml"

    assert source.to_yaml(str(output_file), full_config=False)

    loaded = SSNodeConverter()
    assert loaded.parse_yaml_file(str(output_file))

    assert loaded.remarks == "roundtrip"
    assert loaded.status == "ok"
    assert loaded.nodes == source.nodes
