"""Subscription list command flow."""

from __future__ import annotations

import asyncio
import html
from dataclasses import dataclass
from typing import Any

LIST_SEND_INTERVAL_SECONDS = 0.35


@dataclass(frozen=True)
class ListCommandDeps:
    is_authorized: Any
    send_no_permission_msg: Any
    get_storage: Any
    format_traffic: Any
    get_short_callback_data: Any
    button_labels: dict[str, str]
    telegram_inline_button: Any
    telegram_inline_markup: Any
    schedule_auto_delete: Any


def make_list_command(
    *,
    is_authorized,
    send_no_permission_msg,
    get_storage,
    format_traffic,
    get_short_callback_data,
    button_labels,
    telegram_inline_button,
    telegram_inline_markup,
    schedule_auto_delete,
):
    deps = ListCommandDeps(
        is_authorized=is_authorized,
        send_no_permission_msg=send_no_permission_msg,
        get_storage=get_storage,
        format_traffic=format_traffic,
        get_short_callback_data=get_short_callback_data,
        button_labels=button_labels,
        telegram_inline_button=telegram_inline_button,
        telegram_inline_markup=telegram_inline_markup,
        schedule_auto_delete=schedule_auto_delete,
    )

    async def list_command(update, context):
        if not deps.is_authorized(update):
            await deps.send_no_permission_msg(update)
            return

        uid = update.effective_user.id
        subscriptions = deps.get_storage().get_by_user(uid)
        if not subscriptions:
            await update.message.reply_text("📭 您没有订阅，请先发送订阅链接。")
            return

        await _send_list_header(update, context, subscriptions, deps)
        await _send_grouped_subscriptions(update, uid, subscriptions, deps)

    return list_command


async def _send_list_header(
    update: Any, context: Any, subscriptions: dict[str, Any], deps: ListCommandDeps
) -> None:
    header = f"<b>📋 我的订阅列表 (共 {len(subscriptions)} 个)</b>"
    reply_msg = await update.message.reply_text(header, parse_mode="HTML")
    deps.schedule_auto_delete(context, update.message, reply_msg, delay=30)


async def _send_grouped_subscriptions(
    update: Any, uid: int, subscriptions: dict[str, Any], deps: ListCommandDeps
) -> None:
    tags = sorted({tag for data in subscriptions.values() for tag in data.get("tags", [])})
    for tag in tags:
        tagged_subs = {
            url: data for url, data in subscriptions.items() if tag in data.get("tags", [])
        }
        await _send_subscription_group(update, uid, tagged_subs, deps, tag_label=f"[TAG] {tag}")

    untagged = {url: data for url, data in subscriptions.items() if not data.get("tags")}
    await _send_subscription_group(update, uid, untagged, deps)


async def _send_subscription_group(
    update: Any,
    uid: int,
    subscriptions: dict[str, Any],
    deps: ListCommandDeps,
    *,
    tag_label: str = "",
) -> None:
    for url, data in subscriptions.items():
        await _send_sub_item(update, uid, url, data, deps, tag_label=tag_label)
        await asyncio.sleep(LIST_SEND_INTERVAL_SECONDS)


async def _send_sub_item(
    update: Any,
    uid: int,
    url: str,
    data: dict[str, Any],
    deps: ListCommandDeps,
    *,
    tag_label: str = "",
) -> None:
    msg = _subscription_message(url, data, deps, tag_label=tag_label)
    await update.message.reply_text(
        msg,
        parse_mode="HTML",
        reply_markup=deps.telegram_inline_markup(_subscription_keyboard(url, uid, deps)),
    )


def _subscription_message(
    url: str, data: dict[str, Any], deps: ListCommandDeps, *, tag_label: str = ""
) -> str:
    label = tag_label if tag_label else "📦 未分组"
    msg = f"{label} — <b>{html.escape(data.get('name', '未命名'))}</b>\n<code>{html.escape(url)}</code>"
    if _has_recent_check(data):
        return msg + _recent_check_text(data, deps)
    return msg + "\n最近检测：暂无（可点击下方重新检测）"


def _has_recent_check(data: dict[str, Any]) -> bool:
    values = (data.get("total"), data.get("remaining"), data.get("expire_time"))
    return data.get("last_check_status") == "success" and any(value is not None for value in values)


def _recent_check_text(data: dict[str, Any], deps: ListCommandDeps) -> str:
    total_text = deps.format_traffic(int(data.get("total")))
    remaining = data.get("remaining")
    remain_text = (
        deps.format_traffic(int(remaining)) if isinstance(remaining, (int, float)) else "-"
    )
    return f"\n最近检测：总量 {total_text} | 剩余 {remain_text}\n到期时间：{data.get('expire_time') or '-'}"


def _subscription_keyboard(url: str, uid: int, deps: ListCommandDeps) -> list[list[Any]]:
    return [
        [
            deps.telegram_inline_button(
                deps.button_labels["recheck"],
                callback_data=_build_callback(deps, "recheck", url, uid),
            ),
            deps.telegram_inline_button(
                deps.button_labels["tag"],
                callback_data=_build_callback(deps, "tag", url, uid),
            ),
            deps.telegram_inline_button(
                deps.button_labels["delete"],
                callback_data=_build_callback(deps, "delete", url, uid),
            ),
        ]
    ]


def _build_callback(deps: ListCommandDeps, action: str, url: str, operator_uid: int) -> str:
    try:
        return deps.get_short_callback_data(action, url, operator_uid=operator_uid)
    except TypeError:
        return deps.get_short_callback_data(action, url)
