from __future__ import annotations

import sys
from typing import TypedDict, Optional, Literal

if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    from typing_extensions import NotRequired

class ProxyNode(TypedDict):
    """
    通用代理节点的标准字典规范 (符合 MiHomo YAML 代理结构)，
    用于在各解析器与测试器中流转。
    """
    name: str
    type: str # 'ss', 'vmess', 'trojan', 'vless', 等等
    server: str
    port: int

    # SS 特有
    password: NotRequired[str]

    # Vmess/Vless 特有
    uuid: NotRequired[str]
    alterId: NotRequired[int]
    network: NotRequired[str] # ws, grpc, tcp
    flow: NotRequired[str]    # xtls-rprx-vision 等

    # SS 和 Vmess 协议共用：SS 表示加密方式，Vmess 表示加密算法（通常为 'auto'）
    cipher: NotRequired[str]
    tls: NotRequired[bool]

    # 杂项 / 传输层公共字段
    sni: NotRequired[str]
    skip_cert_verify: NotRequired[bool]
    ws_opts: NotRequired[dict]
    grpc_opts: NotRequired[dict]
    
    # WebSocket options 细分映射
    ws_path: NotRequired[str]
    ws_headers: NotRequired[dict]


class NodeTestResult(TypedDict):
    """
    节点延迟测试产生的结果模型
    """
    name: str
    status: Literal["valid", "error"]
    delay: NotRequired[int]
    error: NotRequired[str]

class SubFetchResult(TypedDict):
    """
    针对单独的一条订阅URL拉取的结果模型
    """
    status: Literal["valid", "invalid", "expired", "error"]
    url: str
    nodes: list[tuple[str, str]] # tuple (类别如 'clash'/'raw', 原始行文本)
