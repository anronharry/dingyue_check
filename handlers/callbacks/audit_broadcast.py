"""Owner broadcast callback actions."""

from __future__ import annotations

from typing import Any

from handlers.commands.admin import deliver_broadcast


async def panel_broadcast_start(query: Any, context: Any, deps: Any) -> bool:
    context.user_data["awaiting_owner_broadcast"] = True
    context.user_data.pop("pending_owner_broadcast_text", None)
    await query.answer("请发送广播内容")
    await query.edit_message_text(
        "已进入广播草稿模式。\n请在下一条消息发送广播正文内容。",
        reply_markup=deps.inline_keyboard_markup(
            [[deps.inline_keyboard_button("取消", callback_data="panel:maint_broadcast_cancel")]]
        ),
    )
    return True


async def panel_broadcast_edit(query: Any, context: Any, deps: Any) -> bool:
    context.user_data["awaiting_owner_broadcast"] = True
    context.user_data.pop("pending_owner_broadcast_text", None)
    await query.answer("请发送新内容")
    await query.edit_message_text(
        "广播草稿已重置。\n请发送新的广播内容。",
        reply_markup=deps.inline_keyboard_markup(
            [[deps.inline_keyboard_button("取消", callback_data="panel:maint_broadcast_cancel")]]
        ),
    )
    return True


async def panel_broadcast_cancel(
    query: Any, context: Any, deps: Any, render_panel_section: Any
) -> bool:
    context.user_data.pop("awaiting_owner_broadcast", None)
    context.user_data.pop("pending_owner_broadcast_text", None)
    await query.answer("已取消广播")
    await render_panel_section(query, "maint_ops", deps)
    return True


async def panel_broadcast_send(
    query: Any,
    context: Any,
    deps: Any,
    owner_panel_section_text: Any,
) -> bool:
    content = (context.user_data.get("pending_owner_broadcast_text") or "").strip()
    if not content:
        await query.answer("没有可发送的广播内容", show_alert=True)
        return True
    if deps.user_manager is None:
        await query.answer("广播功能不可用", show_alert=True)
        return True
    success, failed = await deliver_broadcast(
        bot=context.bot,
        user_ids=deps.user_manager.get_all(),
        content=content,
        logger=deps.logger,
    )
    context.user_data.pop("pending_owner_broadcast_text", None)
    context.user_data.pop("awaiting_owner_broadcast", None)
    await query.answer("广播完成")
    panel = owner_panel_section_text(deps, "maint_ops")
    await query.edit_message_text(
        f"{panel}\n\n广播完成。\n成功: {success}\n失败: {failed}",
        parse_mode="HTML",
        reply_markup=deps.build_owner_panel_keyboard(section="maint_ops"),
    )
    return True
