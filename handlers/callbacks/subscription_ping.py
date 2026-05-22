"""Ping-related subscription callback actions."""

from __future__ import annotations

import html
from typing import Any

from handlers.callbacks.subscription_utils import (
    SubscriptionCallbackDeps,
    has_subscription_access,
    safe_user_error,
    should_auto_remove_failed_subscription,
)

PING_CONCURRENCY = 20
PING_TOP_NODES = 5


async def handle_ping(
    query: Any,
    _context: Any,
    *,
    store: Any,
    url: str,
    operator_uid: int,
    owner_mode: bool,
    deps: SubscriptionCallbackDeps,
) -> bool:
    await query.answer("🚀 开始连通性测试，请稍候...")
    await query.edit_message_text("🚀 正在执行并发测速，请稍候...")
    try:
        await _assert_ping_access(store, url, operator_uid, owner_mode)
        nodes = await _load_nodes_for_ping(url, deps)
        if not nodes:
            await query.edit_message_text("当前格式不支持直接获取节点列表测速。")
            return True
        alive_count, total_count, alive_nodes = await deps.latency_tester.ping_all_nodes(
            nodes, concurrency=PING_CONCURRENCY
        )
        if await _delete_dead_subscription(
            query, store, url, operator_uid, owner_mode, alive_count, total_count
        ):
            return True
        await _send_ping_report(query, alive_count, total_count, alive_nodes)
    except Exception as exc:
        await _reply_ping_failure(query, store, url, operator_uid, owner_mode, exc, deps)
    return True


async def _assert_ping_access(store: Any, url: str, operator_uid: int, owner_mode: bool) -> None:
    sub_owner = int(store.get_all().get(url, {}).get("owner_uid", 0) or 0)
    if not has_subscription_access(
        sub_owner_uid=sub_owner, operator_uid=operator_uid, owner_mode=owner_mode
    ):
        raise PermissionError("无权操作他人的订阅。")


async def _load_nodes_for_ping(url: str, deps: SubscriptionCallbackDeps) -> list[dict[str, Any]]:
    parser_instance = await deps.get_parser()
    result = await parser_instance.parse(url)
    return result.get("_normalized_nodes") or result.get("_raw_nodes", [])


async def _delete_dead_subscription(
    query: Any,
    store: Any,
    url: str,
    operator_uid: int,
    owner_mode: bool,
    alive_count: int,
    total_count: int,
) -> bool:
    if total_count <= 0 or alive_count != 0:
        return False
    removed = store.remove(url, operator_uid=operator_uid, require_owner=not owner_mode)
    if removed:
        await query.edit_message_text("❌ 测速结果为 0 存活，已自动删除该订阅记录。")
    else:
        await query.edit_message_text("❌ 测速结果为 0 存活，自动删除失败（无权限或记录不存在）。")
    return True


async def _send_ping_report(
    query: Any, alive_count: int, total_count: int, alive_nodes: list[dict[str, Any]]
) -> None:
    await query.message.reply_text(
        _build_ping_report(alive_count, total_count, alive_nodes), parse_mode="HTML"
    )
    await query.message.delete()


def _build_ping_report(
    alive_count: int, total_count: int, alive_nodes: list[dict[str, Any]]
) -> str:
    ping_report = (
        "<b>测速报告</b>\n"
        f"总计: {total_count} | 存活: {alive_count} | 失败: {total_count - alive_count}\n"
        "--------------------\n"
    )
    if alive_nodes:
        ping_report += "\n<b>Top 5 最快节点</b>\n"
        for index, node in enumerate(alive_nodes[:PING_TOP_NODES], start=1):
            ping_report += (
                f"{index}. {html.escape(node['name'])} - <code>{node['latency']}ms</code>\n"
            )
    return ping_report


async def _reply_ping_failure(
    query: Any,
    store: Any,
    url: str,
    operator_uid: int,
    owner_mode: bool,
    exc: Exception,
    deps: SubscriptionCallbackDeps,
) -> None:
    deps.logger.error("测速过程中发生错误: %s", exc)
    if isinstance(exc, PermissionError):
        await query.edit_message_text(str(exc))
        return
    auto_removed = False
    if should_auto_remove_failed_subscription(exc):
        auto_removed = store.remove(url, operator_uid=operator_uid, require_owner=not owner_mode)
    message = f"❌ 测速失败：{safe_user_error(exc)}"
    if auto_removed:
        message += "\n已自动删除该失效订阅。"
    await query.edit_message_text(message)
