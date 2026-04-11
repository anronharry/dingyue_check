from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
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


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    WARNING = "warning"
    FAILED = "failed"


def _parse_expire_date(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


@dataclass(slots=True)
class SubscriptionEntity:
    url: str
    name: str
    remaining_bytes: int = 0
    expire_date: datetime | None = None
    owner_uid: int | None = None
    error: str | None = None

    @classmethod
    def from_parse_result(cls, *, url: str, result: dict, owner_uid: int | None = None) -> "SubscriptionEntity":
        remaining = result.get("remaining")
        if not isinstance(remaining, int):
            try:
                remaining = int(remaining or 0)
            except Exception:
                remaining = 0
        return cls(
            url=url,
            name=str(result.get("name") or "未知"),
            remaining_bytes=max(0, remaining),
            expire_date=_parse_expire_date(result.get("expire_time")),
            owner_uid=owner_uid,
            error=None,
        )

    @classmethod
    def from_failure(
        cls,
        *,
        url: str,
        name: str,
        error: str,
        owner_uid: int | None = None,
    ) -> "SubscriptionEntity":
        return cls(
            url=url,
            name=name or "未知",
            remaining_bytes=0,
            expire_date=None,
            owner_uid=owner_uid,
            error=error or "未知错误",
        )

    @property
    def is_low_traffic(self) -> bool:
        return 0 < self.remaining_bytes < 5 * 1024 * 1024 * 1024

    @property
    def is_expiring_soon(self) -> bool:
        if self.expire_date is None:
            return False
        return self.expire_date <= datetime.now() + timedelta(days=3)

    @property
    def status(self) -> SubscriptionStatus:
        if self.error:
            return SubscriptionStatus.FAILED
        if self.is_low_traffic or self.is_expiring_soon:
            return SubscriptionStatus.WARNING
        return SubscriptionStatus.ACTIVE


@dataclass(slots=True)
class BatchCheckResult:
    entries: list[SubscriptionEntity] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def success(self) -> list[SubscriptionEntity]:
        return [entry for entry in self.entries if entry.status != SubscriptionStatus.FAILED]

    @property
    def failed(self) -> list[SubscriptionEntity]:
        return [entry for entry in self.entries if entry.status == SubscriptionStatus.FAILED]

    @property
    def warning(self) -> list[SubscriptionEntity]:
        return [entry for entry in self.entries if entry.status == SubscriptionStatus.WARNING]

    @property
    def active(self) -> list[SubscriptionEntity]:
        return [entry for entry in self.entries if entry.status == SubscriptionStatus.ACTIVE]
