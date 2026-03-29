"""Top-level callback router."""
from __future__ import annotations


def make_button_callback(*, is_authorized, no_permission_alert, subscription_callback_handler):
    async def button_callback(update, context):
        query = update.callback_query
        try:
            action, hash_key = query.data.split(":", 1)
        except ValueError:
            await query.answer("数据异常", show_alert=True)
            return
        await query.answer()
        if action not in {"audit", "audit_detail", "recent", "recent_detail", "panel"} and not is_authorized(update):
            await query.answer(no_permission_alert, show_alert=True)
            return
        handled = await subscription_callback_handler(update, context, action, hash_key)
        if not handled:
            await query.answer("未知操作", show_alert=True)

    return button_callback
