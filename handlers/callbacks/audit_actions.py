"""Owner-facing usage audit callback actions."""
from __future__ import annotations

import asyncio
import os

from handlers.commands.admin import create_backup_file, deliver_broadcast, export_subscriptions_file
from renderers.messages.admin_reports import (
    render_global_list,
    render_owner_panel_section_text,
    render_owner_panel_text,
    render_recent_exports_summary,
    render_recent_users_summary,
    render_usage_audit_summary,
    render_user_list,
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
    def _owner_panel_data():
        return admin_service.get_owner_panel_data()

    def _owner_panel_section_data(section: str):
        return admin_service.get_owner_panel_section_data(section)

    def _owner_panel_text() -> str:
        total_users, daily_users = admin_service.get_usage_user_counts(include_owner=False)
        data = admin_service.get_owner_panel_data()
        return render_owner_panel_text(data, total_users=total_users, daily_users=daily_users)

    def _owner_panel_section_text(section: str) -> str:
        return render_owner_panel_section_text(section, _owner_panel_section_data(section))

    def _usage_audit_report(mode: str):
        data = admin_service.get_usage_audit_summary(mode=mode)
        return render_usage_audit_summary(data), {"mode": data["mode"]}

    def _recent_report(category: str, include_owner: bool):
        if category == "exports":
            data = admin_service.get_recent_exports_summary(include_owner=include_owner, limit=10)
            return render_recent_exports_summary(data), {"scope": data["scope"]}
        data = admin_service.get_recent_users_summary(include_owner=include_owner, limit=10)
        return render_recent_users_summary(data), {"scope": data["scope"]}

    def _globallist_report() -> str:
        return render_global_list(admin_service.get_globallist_data())

    def _user_list_report() -> str:
        return render_user_list(admin_service.get_user_list_data())

    def _panel_keyboard_section(target: str) -> str:
        if target == "maint_ops":
            return "maint_ops"
        if target == "maint_backup":
            return "maint_backup"
        if target.startswith("maint_"):
            return "maintenance"
        return target

    def _build_panel_text() -> str:
        return _owner_panel_text()

    async def _render_panel_section(query, section: str) -> None:
        await query.edit_message_text(
            _owner_panel_section_text(section),
            parse_mode="HTML",
            reply_markup=build_owner_panel_keyboard(section=_panel_keyboard_section(section)),
        )

    async def _panel_root(query, _context) -> bool:
        await query.edit_message_text(
            _build_panel_text(),
            parse_mode="HTML",
            reply_markup=build_owner_panel_keyboard(section="root"),
        )
        return True

    async def _panel_maint_access(query, _context, *, enabled: bool) -> bool:
        if access_service is None:
            await query.answer("操作不可用", show_alert=True)
            return True
        changed, saved = access_service.set_allow_all_users(enabled)
        if not saved:
            await query.answer("保存失败", show_alert=True)
            return True
        if enabled:
            tip = "已开启公开访问模式。" if changed else "公开访问模式已是开启状态。"
        else:
            tip = "已关闭公开访问模式。" if changed else "公开访问模式已是关闭状态。"
        await query.answer("已更新")
        panel = _owner_panel_section_text("maint_access")
        await query.edit_message_text(
            f"{panel}\n\n{tip}",
            parse_mode="HTML",
            reply_markup=build_owner_panel_keyboard(section="maintenance"),
        )
        return True

    async def _panel_refresh_menu(query, context) -> bool:
        if post_init is None:
            await query.answer("刷新功能不可用", show_alert=True)
            return True
        await query.answer("正在刷新菜单...")
        try:
            await post_init(context.application)
            tip = "命令菜单刷新完成。"
        except Exception:
            tip = "命令菜单刷新失败。"
        panel = _owner_panel_section_text("maint_ops")
        await query.edit_message_text(
            f"{panel}\n\n{tip}",
            parse_mode="HTML",
            reply_markup=build_owner_panel_keyboard(section="maint_ops"),
        )
        return True

    async def _panel_export_json(query, _context) -> bool:
        if get_storage is None:
            await query.answer("操作不可用", show_alert=True)
            return True
        await query.answer("正在导出...")
        store = get_storage()
        ok, export_file, export_name, total = await export_subscriptions_file(store=store, admin_service=admin_service)
        if not ok:
            panel = _owner_panel_section_text("maint_backup")
            await query.edit_message_text(
                f"{panel}\n\n导出失败，请稍后重试。",
                parse_mode="HTML",
                reply_markup=build_owner_panel_keyboard(section="maint_backup"),
            )
            return True
        try:
            with open(export_file, "rb") as handle:
                await query.message.reply_document(
                    document=handle,
                    filename=export_name,
                    caption=f"导出完成，共 {total} 条订阅。",
                )
        finally:
            try:
                await asyncio.get_event_loop().run_in_executor(None, os.remove, export_file)
            except OSError:
                pass
        panel = _owner_panel_section_text("maint_backup")
        await query.edit_message_text(
            f"{panel}\n\n导出完成，文件已发送。",
            parse_mode="HTML",
            reply_markup=build_owner_panel_keyboard(section="maint_backup"),
        )
        return True

    async def _panel_backup_now(query, _context) -> bool:
        if backup_service is None:
            await query.answer("操作不可用", show_alert=True)
            return True
        await query.answer("正在生成备份...")
        zip_path, zip_name = await create_backup_file(backup_service=backup_service)
        with open(zip_path, "rb") as handle:
            caption = admin_service.build_backup_caption(zip_name=zip_name)
            await query.message.reply_document(document=handle, filename=zip_name, caption=caption, parse_mode="HTML")
        panel = _owner_panel_section_text("maint_backup")
        await query.edit_message_text(
            f"{panel}\n\n全量备份已生成并发送。",
            parse_mode="HTML",
            reply_markup=build_owner_panel_keyboard(section="maint_backup"),
        )
        return True

    async def _panel_import_start(query, context) -> bool:
        context.user_data["awaiting_import"] = True
        context.user_data.pop("awaiting_restore", None)
        await query.answer("等待上传 JSON")
        await query.edit_message_text(
            "已进入导入模式。\n请上传由导出功能生成的 JSON 文件，我会自动执行导入。",
            reply_markup=inline_keyboard_markup(
                [[inline_keyboard_button("返回备份页", callback_data="panel:maint_backup")]]
            ),
        )
        return True

    async def _panel_restore_start(query, context) -> bool:
        context.user_data["awaiting_restore"] = True
        context.user_data.pop("awaiting_import", None)
        await query.answer("等待上传 ZIP")
        await query.edit_message_text(
            "已进入恢复模式。\n请上传由备份功能生成的 ZIP 文件，我会自动执行恢复。",
            reply_markup=inline_keyboard_markup(
                [[inline_keyboard_button("返回备份页", callback_data="panel:maint_backup")]]
            ),
        )
        return True

    async def _panel_broadcast_start(query, context) -> bool:
        context.user_data["awaiting_owner_broadcast"] = True
        context.user_data.pop("pending_owner_broadcast_text", None)
        await query.answer("请发送广播内容")
        await query.edit_message_text(
            "已进入广播草稿模式。\n请在下一条消息发送广播正文内容。",
            reply_markup=inline_keyboard_markup(
                [[inline_keyboard_button("取消", callback_data="panel:maint_broadcast_cancel")]]
            ),
        )
        return True

    async def _panel_broadcast_edit(query, context) -> bool:
        context.user_data["awaiting_owner_broadcast"] = True
        context.user_data.pop("pending_owner_broadcast_text", None)
        await query.answer("请发送新内容")
        await query.edit_message_text(
            "广播草稿已重置。\n请发送新的广播内容。",
            reply_markup=inline_keyboard_markup(
                [[inline_keyboard_button("取消", callback_data="panel:maint_broadcast_cancel")]]
            ),
        )
        return True

    async def _panel_broadcast_cancel(query, context) -> bool:
        context.user_data.pop("awaiting_owner_broadcast", None)
        context.user_data.pop("pending_owner_broadcast_text", None)
        await query.answer("已取消广播")
        await _render_panel_section(query, "maint_ops")
        return True

    async def _panel_broadcast_send(query, context) -> bool:
        content = (context.user_data.get("pending_owner_broadcast_text") or "").strip()
        if not content:
            await query.answer("没有可发送的广播内容", show_alert=True)
            return True
        if user_manager is None:
            await query.answer("广播功能不可用", show_alert=True)
            return True
        success, failed = await deliver_broadcast(
            bot=context.bot,
            user_ids=user_manager.get_all(),
            content=content,
            logger=logger,
        )
        context.user_data.pop("pending_owner_broadcast_text", None)
        context.user_data.pop("awaiting_owner_broadcast", None)
        await query.answer("广播完成")
        panel = _owner_panel_section_text("maint_ops")
        await query.edit_message_text(
            f"{panel}\n\n广播完成。\n成功: {success}\n失败: {failed}",
            parse_mode="HTML",
            reply_markup=build_owner_panel_keyboard(section="maint_ops"),
        )
        return True

    async def _panel_listusers(query, _context) -> bool:
        report = _user_list_report_compat()
        await query.edit_message_text(
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_keyboard_markup([[inline_keyboard_button("返回用户页", callback_data="panel:users")]]),
        )
        return True

    async def _panel_audit(query, _context) -> bool:
        report, payload = _usage_audit_report("others")
        await query.edit_message_text(
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=build_usage_audit_keyboard(mode=payload["mode"]),
        )
        return True

    async def _panel_recentusers(query, _context) -> bool:
        report, payload = _recent_report("users", include_owner=False)
        await query.edit_message_text(
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=build_recent_activity_keyboard(
                category="users",
                scope=payload["scope"],
            ),
        )
        return True

    async def _panel_recentexports(query, _context) -> bool:
        report, payload = _recent_report("exports", include_owner=False)
        await query.edit_message_text(
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=build_recent_activity_keyboard(
                category="exports",
                scope=payload["scope"],
            ),
        )
        return True

    async def _panel_globallist(query, _context) -> bool:
        report = _globallist_report_compat()
        await query.edit_message_text(
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_keyboard_markup([[inline_keyboard_button("返回总览页", callback_data="panel:overview")]]),
        )
        return True

    panel_handlers = {
        "root": _panel_root,
        "maint_access_enable": lambda q, c: _panel_maint_access(q, c, enabled=True),
        "maint_access_disable": lambda q, c: _panel_maint_access(q, c, enabled=False),
        "maint_refresh_menu": _panel_refresh_menu,
        "maint_export_json": _panel_export_json,
        "maint_backup_now": _panel_backup_now,
        "maint_import_start": _panel_import_start,
        "maint_restore_start": _panel_restore_start,
        "maint_broadcast_start": _panel_broadcast_start,
        "maint_broadcast_edit": _panel_broadcast_edit,
        "maint_broadcast_cancel": _panel_broadcast_cancel,
        "maint_broadcast_send": _panel_broadcast_send,
        "overview": lambda q, c: _render_panel_section(q, "overview"),
        "users": lambda q, c: _render_panel_section(q, "users"),
        "maintenance": lambda q, c: _render_panel_section(q, "maintenance"),
        "maint_backup": lambda q, c: _render_panel_section(q, "maint_backup"),
        "maint_access": lambda q, c: _render_panel_section(q, "maint_access"),
        "maint_ops": lambda q, c: _render_panel_section(q, "maint_ops"),
        "listusers": _panel_listusers,
        "audit": _panel_audit,
        "recentusers": _panel_recentusers,
        "recentexports": _panel_recentexports,
        "globallist": _panel_globallist,
    }

    async def handle_callback(update, context, action: str, hash_key: str) -> bool:
        query = update.callback_query
        if action not in {"audit", "audit_detail", "recent", "recent_detail", "panel"}:
            return False
        if not is_owner(update):
            await query.answer("只有管理员可以查看。", show_alert=True)
            return True

        if action == "panel":
            await query.answer("打开控制台...")
            target = hash_key
            handler = panel_handlers.get(target)
            if handler is not None:
                await handler(query, context)
                return True
            await _panel_root(query, context)
            return True

        if action == "audit":
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

        if action == "recent":
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


        await query.answer("明细页已下线，请使用汇总视图。", show_alert=True)
        return True

    return handle_callback
