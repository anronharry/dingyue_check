"""Operational subscription callback actions."""

from __future__ import annotations

import html
from typing import Any

from handlers.callbacks.subscription_utils import (
    SubscriptionCallbackDeps,
    build_callback,
    has_subscription_access,
    make_sub_keyboard_safe,
    safe_user_error,
    should_auto_remove_failed_subscription,
)


async def handle_more_ops(
    query: Any,
    _context: Any,
    *,
    url: str,
    owner_mode: bool,
    operator_uid: int,
    deps: SubscriptionCallbackDeps,
) -> bool:
    await query.answer("已展开导出功能，可下载 YAML/TXT")
    await _edit_keyboard(
        query, url=url, owner_mode=owner_mode, operator_uid=operator_uid, expanded=True, deps=deps
    )
    return True


async def handle_basic_ops(
    query: Any,
    _context: Any,
    *,
    url: str,
    owner_mode: bool,
    operator_uid: int,
    deps: SubscriptionCallbackDeps,
) -> bool:
    await query.answer("已收起，仅保留核心操作")
    await _edit_keyboard(
        query, url=url, owner_mode=owner_mode, operator_uid=operator_uid, expanded=False, deps=deps
    )
    return True


async def _edit_keyboard(
    query: Any,
    *,
    url: str,
    owner_mode: bool,
    operator_uid: int,
    expanded: bool,
    deps: SubscriptionCallbackDeps,
) -> None:
    await query.edit_message_reply_markup(
        reply_markup=make_sub_keyboard_safe(
            deps,
            url=url,
            operator_uid=operator_uid,
            owner_mode=owner_mode,
            user_actions_expanded=expanded,
        )
    )


async def handle_recheck(
    update: Any,
    query: Any,
    _context: Any,
    *,
    store: Any,
    url: str,
    owner_mode: bool,
    operator_uid: int,
    deps: SubscriptionCallbackDeps,
) -> bool:
    await query.answer("🔄 正在重新检测，请稍候...")
    await query.edit_message_text("🔄 正在重新检测，请稍候...")
    try:
        result = await _parse_and_store_recheck(store, url, owner_mode, operator_uid, deps)
        deps.usage_audit_service.log_check(
            user=update.effective_user, urls=[url], source="按钮重检"
        )
        await query.edit_message_text(
            deps.format_subscription_info(result, url),
            parse_mode="HTML",
            reply_markup=make_sub_keyboard_safe(
                deps, url=url, operator_uid=operator_uid, owner_mode=owner_mode
            ),
        )
    except Exception as exc:
        await _reply_recheck_failure(query, store, url, operator_uid, owner_mode, exc, deps)
    return True


async def _parse_and_store_recheck(
    store: Any,
    url: str,
    owner_mode: bool,
    operator_uid: int,
    deps: SubscriptionCallbackDeps,
) -> dict[str, Any]:
    sub = store.get_all().get(url, {})
    owner_uid = int(sub.get("owner_uid", 0) or 0)
    if not has_subscription_access(
        sub_owner_uid=owner_uid, operator_uid=operator_uid, owner_mode=owner_mode
    ):
        raise PermissionError("无权操作他人的订阅。")
    if deps.subscription_check_service:
        return await deps.subscription_check_service.parse_and_store(url=url, owner_uid=owner_uid)
    parser_instance = await deps.get_parser()
    result = await parser_instance.parse(url)
    store.add_or_update(url, result, user_id=owner_uid)
    deps.export_cache_service.save_subscription_cache(
        owner_uid=owner_uid, source=url, result=result
    )
    return result


async def _reply_recheck_failure(
    query: Any,
    store: Any,
    url: str,
    operator_uid: int,
    owner_mode: bool,
    exc: Exception,
    deps: SubscriptionCallbackDeps,
) -> None:
    if isinstance(exc, PermissionError):
        await query.edit_message_text(str(exc))
        return
    store.mark_check_failed(url, str(exc), operator_uid=operator_uid, require_owner=not owner_mode)
    auto_removed = False
    if should_auto_remove_failed_subscription(exc):
        auto_removed = store.remove(url, operator_uid=operator_uid, require_owner=not owner_mode)
    error_msg = f"❌ 重新检测失败：{safe_user_error(exc)}"
    if auto_removed:
        error_msg += "\n已自动删除该失效订阅。"
    await query.edit_message_text(error_msg)


async def handle_delete_prompt(
    query: Any,
    _context: Any,
    *,
    store: Any,
    url: str,
    operator_uid: int,
    owner_mode: bool,
    deps: SubscriptionCallbackDeps,
) -> bool:
    await query.answer("请确认是否删除")
    sub = store.get_all().get(url, {})
    sub_owner = int(sub.get("owner_uid", 0) or 0)
    if not has_subscription_access(
        sub_owner_uid=sub_owner, operator_uid=operator_uid, owner_mode=owner_mode
    ):
        await query.edit_message_text("无权操作他人的订阅。")
        return True
    keyboard = [
        [
            deps.inline_keyboard_button(
                deps.confirm_delete_label,
                callback_data=build_callback(deps, "del_confirm", url, operator_uid),
            ),
            deps.inline_keyboard_button(
                "返回", callback_data=build_callback(deps, "recheck", url, operator_uid)
            ),
        ]
    ]
    await query.edit_message_text(
        f"<b>确定删除这个订阅吗？</b>\n\n名称：{html.escape(sub.get('name', url))}\n此操作不可撤销。",
        parse_mode="HTML",
        reply_markup=deps.inline_keyboard_markup(keyboard),
    )
    return True


async def handle_delete_confirm(
    query: Any, _context: Any, *, store: Any, url: str, operator_uid: int, owner_mode: bool
) -> bool:
    await query.answer("正在执行删除...")
    if store.remove(url, operator_uid=operator_uid, require_owner=not owner_mode):
        await query.edit_message_text("<b>订阅已永久移除</b>", parse_mode="HTML")
    else:
        await query.edit_message_text("删除失败：无权限或记录已不存在")
    return True


async def handle_delete_cancel(query: Any, _context: Any) -> bool:
    await query.answer("已取消")
    await query.edit_message_text("<b>已取消删除操作</b>", parse_mode="HTML")
    return True


async def handle_mute_alerts(
    query: Any, _context: Any, *, operator_uid: int, deps: SubscriptionCallbackDeps
) -> bool:
    if not deps.alert_preference_service:
        await query.answer("当前版本不支持该操作", show_alert=True)
        return True
    deps.alert_preference_service.mute_user(operator_uid)
    await query.answer("已关闭预警提醒")
    await _edit_alert_keyboard(query, "🔔 恢复预警提醒", "unmute_alerts:on", deps)
    return True


async def handle_unmute_alerts(
    query: Any, _context: Any, *, operator_uid: int, deps: SubscriptionCallbackDeps
) -> bool:
    if not deps.alert_preference_service:
        await query.answer("当前版本不支持该操作", show_alert=True)
        return True
    deps.alert_preference_service.unmute_user(operator_uid)
    await query.answer("已恢复预警提醒")
    await _edit_alert_keyboard(query, "🔕 关闭预警提醒", "mute_alerts:off", deps)
    return True


async def _edit_alert_keyboard(
    query: Any, label: str, callback_data: str, deps: SubscriptionCallbackDeps
) -> None:
    try:
        await query.edit_message_reply_markup(
            reply_markup=deps.inline_keyboard_markup(
                [[deps.inline_keyboard_button(label, callback_data=callback_data)]]
            )
        )
    except Exception:
        pass
