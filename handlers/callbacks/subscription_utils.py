"""Shared helpers for subscription callback actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

AUTO_REMOVE_ERROR_CODES = {"auth_error", "not_found", "invalid_content", "ssl_error"}
AUTO_REMOVE_ERROR_SNIPPETS = (
    "已失效",
    "不存在",
    "无法识别订阅内容",
    "流量已耗尽",
    "流量已完全耗尽",
    "剩余 0 B",
    "SSL 证书校验失败",
)


@dataclass(frozen=True)
class SubscriptionCallbackDeps:
    get_parser: Any
    format_subscription_info: Any
    make_sub_keyboard: Any
    cleanup_url_cache: Any
    url_cache: dict[str, Any]
    tag_forbidden_msg: str
    tag_exists_alert: str
    confirm_delete_label: str
    inline_keyboard_button: Any
    inline_keyboard_markup: Any
    get_short_callback_data: Any
    latency_tester: Any
    usage_audit_service: Any
    export_cache_service: Any
    logger: Any
    subscription_check_service: Any = None
    alert_preference_service: Any = None


def safe_user_error(exc: Exception, *, fallback: str = "操作失败，请稍后重试。") -> str:
    msg = str(exc or "").strip().splitlines()[0]
    if not msg:
        return fallback
    if len(msg) > 120:
        return msg[:120] + "..."
    return msg


def should_auto_remove_failed_subscription(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "").strip().lower()
    if code in AUTO_REMOVE_ERROR_CODES:
        return True
    error_text = str(exc or "")
    return any(token in error_text for token in AUTO_REMOVE_ERROR_SNIPPETS)


def build_callback(deps: SubscriptionCallbackDeps, action: str, url: str, operator_uid: int) -> str:
    try:
        return deps.get_short_callback_data(action, url, operator_uid=operator_uid)
    except TypeError:
        return deps.get_short_callback_data(action, url)


def make_sub_keyboard_safe(
    deps: SubscriptionCallbackDeps,
    *,
    url: str,
    operator_uid: int,
    owner_mode: bool,
    user_actions_expanded: bool = False,
) -> Any:
    try:
        return deps.make_sub_keyboard(
            url,
            operator_uid=operator_uid,
            owner_mode=owner_mode,
            user_actions_expanded=user_actions_expanded,
        )
    except TypeError:
        return _make_legacy_keyboard(deps, url, owner_mode, user_actions_expanded)


def _make_legacy_keyboard(
    deps: SubscriptionCallbackDeps, url: str, owner_mode: bool, user_actions_expanded: bool
) -> Any:
    try:
        return deps.make_sub_keyboard(
            url, owner_mode=owner_mode, user_actions_expanded=user_actions_expanded
        )
    except TypeError:
        return deps.make_sub_keyboard(url, owner_mode=owner_mode)


def resolve_url(deps: SubscriptionCallbackDeps, hash_key: str, *, operator_uid: int) -> str | None:
    deps.cleanup_url_cache()
    cache_entry = deps.url_cache.get(hash_key, {})
    cache_uid = int(cache_entry.get("uid", 0) or 0)
    if cache_uid and cache_uid != operator_uid:
        return None
    return cache_entry.get("url")


def has_subscription_access(*, sub_owner_uid: int, operator_uid: int, owner_mode: bool) -> bool:
    if owner_mode:
        return True
    if sub_owner_uid <= 0:
        return True
    return sub_owner_uid == operator_uid
