"""Owner-facing usage audit callback actions."""

from __future__ import annotations

from handlers.callbacks.audit_panel import AuditPanelDeps, handle_panel_action
from renderers.messages.admin_reports import (
    render_recent_exports_summary,
    render_recent_users_summary,
    render_usage_audit_summary,
)


def make_audit_callback_handler(
    *,
    is_owner,
    admin_service,
    access_service=None,
    post_init=None,
    user_manager=None,
    get_storage=None,
    backup_service=None,
    logger=None,
    build_usage_audit_keyboard,
    build_recent_activity_keyboard,
    build_owner_panel_keyboard,
    inline_keyboard_button,
    inline_keyboard_markup,
):
    panel_deps = AuditPanelDeps(
        admin_service=admin_service,
        access_service=access_service,
        post_init=post_init,
        user_manager=user_manager,
        get_storage=get_storage,
        backup_service=backup_service,
        logger=logger,
        build_owner_panel_keyboard=build_owner_panel_keyboard,
        inline_keyboard_button=inline_keyboard_button,
        inline_keyboard_markup=inline_keyboard_markup,
    )

    def _usage_audit_report(mode: str):
        data = admin_service.get_usage_audit_summary(mode=mode)
        return render_usage_audit_summary(data), {"mode": data["mode"]}

    def _recent_report(category: str, include_owner: bool):
        if category == "exports":
            data = admin_service.get_recent_exports_summary(include_owner=include_owner, limit=10)
            return render_recent_exports_summary(data), {"scope": data["scope"]}
        data = admin_service.get_recent_users_summary(include_owner=include_owner, limit=10)
        return render_recent_users_summary(data), {"scope": data["scope"]}

    async def _handle_audit(query, hash_key: str) -> bool:
        await query.answer("加载审计汇总...")
        mode = hash_key.split(":", 1)[0] if hash_key else "others"
        if mode not in {"others", "owner", "all"}:
            mode = "others"
        report, payload = _usage_audit_report(mode)
        await query.edit_message_text(
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=build_usage_audit_keyboard(mode=payload["mode"]),
        )
        return True

    async def _handle_recent(query, hash_key: str) -> bool:
        await query.answer("加载最近记录汇总...")
        try:
            category, scope = hash_key.split(":", 1)
        except ValueError:
            category, scope = "users", "others"
        include_owner = scope == "all"
        report, payload = _recent_report(category, include_owner=include_owner)
        await query.edit_message_text(
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=build_recent_activity_keyboard(
                category=category,
                scope=payload["scope"],
            ),
        )
        return True

    async def _handle_panel(query, context, hash_key: str) -> bool:
        await query.answer("打开控制台...")
        if hash_key == "audit":
            return await _handle_audit(query, "others")
        if hash_key == "recentusers":
            return await _handle_recent(query, "users:others")
        if hash_key == "recentexports":
            return await _handle_recent(query, "exports:others")
        return await handle_panel_action(query, context, hash_key, panel_deps, answer=False)

    async def handle_callback(update, context, action: str, hash_key: str) -> bool:
        query = update.callback_query
        if action not in {"audit", "audit_detail", "recent", "recent_detail", "panel"}:
            return False
        if not is_owner(update):
            await query.answer("只有管理员可以查看。", show_alert=True)
            return True

        if action == "panel":
            return await _handle_panel(query, context, hash_key)
        if action == "audit":
            return await _handle_audit(query, hash_key)
        if action == "recent":
            return await _handle_recent(query, hash_key)

        await query.answer("明细页已下线，请使用汇总视图。", show_alert=True)
        return True

    return handle_callback
