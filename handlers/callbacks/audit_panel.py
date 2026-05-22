"""Owner panel callback actions for audit callbacks."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from handlers.callbacks.audit_broadcast import (
    panel_broadcast_cancel,
    panel_broadcast_edit,
    panel_broadcast_send,
    panel_broadcast_start,
)
from handlers.commands.admin import create_backup_file, export_subscriptions_file
from renderers.messages.admin_reports import (
    render_global_list,
    render_owner_panel_section_text,
    render_owner_panel_text,
    render_user_list,
)


@dataclass(frozen=True)
class AuditPanelDeps:
    admin_service: Any
    access_service: Any
    post_init: Any
    user_manager: Any
    get_storage: Any
    backup_service: Any
    logger: Any
    build_owner_panel_keyboard: Any
    inline_keyboard_button: Any
    inline_keyboard_markup: Any


def owner_panel_section_text(deps: AuditPanelDeps, section: str) -> str:
    data = deps.admin_service.get_owner_panel_section_data(section)
    return render_owner_panel_section_text(section, data)


def owner_panel_text(deps: AuditPanelDeps) -> str:
    total_users, daily_users = deps.admin_service.get_usage_user_counts(include_owner=False)
    data = deps.admin_service.get_owner_panel_data()
    return render_owner_panel_text(data, total_users=total_users, daily_users=daily_users)


def panel_keyboard_section(target: str) -> str:
    if target == "maint_ops":
        return "maint_ops"
    if target == "maint_backup":
        return "maint_backup"
    if target == "maint_access":
        return "maint_access"
    if target.startswith("maint_"):
        return "maintenance"
    return target


async def handle_panel_action(
    query: Any, context: Any, target: str, deps: AuditPanelDeps, *, answer: bool = True
) -> bool:
    if answer:
        await query.answer("打开控制台...")
    handlers = _build_panel_handlers(deps)
    handler = handlers.get(target)
    if handler is not None:
        await handler(query, context)
        return True
    await panel_root(query, context, deps)
    return True


def _build_panel_handlers(deps: AuditPanelDeps) -> dict[str, Any]:
    return {
        "root": lambda q, c: panel_root(q, c, deps),
        "maint_access_enable": lambda q, c: panel_maint_access(q, c, deps, enabled=True),
        "maint_access_disable": lambda q, c: panel_maint_access(q, c, deps, enabled=False),
        "maint_refresh_menu": lambda q, c: panel_refresh_menu(q, c, deps),
        "maint_export_json": lambda q, c: panel_export_json(q, c, deps),
        "maint_backup_now": lambda q, c: panel_backup_now(q, c, deps),
        "maint_import_start": lambda q, c: panel_import_start(q, c, deps),
        "maint_restore_start": lambda q, c: panel_restore_start(q, c, deps),
        "maint_broadcast_start": lambda q, c: panel_broadcast_start(q, c, deps),
        "maint_broadcast_edit": lambda q, c: panel_broadcast_edit(q, c, deps),
        "maint_broadcast_cancel": lambda q, c: panel_broadcast_cancel(
            q, c, deps, render_panel_section
        ),
        "maint_broadcast_send": lambda q, c: panel_broadcast_send(
            q, c, deps, owner_panel_section_text
        ),
        "overview": lambda q, c: render_panel_section(q, "overview", deps),
        "users": lambda q, c: render_panel_section(q, "users", deps),
        "maintenance": lambda q, c: render_panel_section(q, "maintenance", deps),
        "maint_backup": lambda q, c: render_panel_section(q, "maint_backup", deps),
        "maint_access": lambda q, c: render_panel_section(q, "maint_access", deps),
        "maint_ops": lambda q, c: render_panel_section(q, "maint_ops", deps),
        "listusers": lambda q, c: panel_listusers(q, c, deps),
        "globallist": lambda q, c: panel_globallist(q, c, deps),
    }


async def render_panel_section(query: Any, section: str, deps: AuditPanelDeps) -> None:
    await query.edit_message_text(
        owner_panel_section_text(deps, section),
        parse_mode="HTML",
        reply_markup=deps.build_owner_panel_keyboard(section=panel_keyboard_section(section)),
    )


async def panel_root(query: Any, _context: Any, deps: AuditPanelDeps) -> bool:
    await query.edit_message_text(
        owner_panel_text(deps),
        parse_mode="HTML",
        reply_markup=deps.build_owner_panel_keyboard(section="root"),
    )
    return True


async def panel_maint_access(
    query: Any, _context: Any, deps: AuditPanelDeps, *, enabled: bool
) -> bool:
    if deps.access_service is None:
        await query.answer("操作不可用", show_alert=True)
        return True
    changed, saved = deps.access_service.set_allow_all_users(enabled)
    if not saved:
        await query.answer("保存失败", show_alert=True)
        return True
    tip = _access_tip(enabled=enabled, changed=changed)
    await query.answer("已更新")
    panel = owner_panel_section_text(deps, "maint_access")
    await query.edit_message_text(
        f"{panel}\n\n{tip}",
        parse_mode="HTML",
        reply_markup=deps.build_owner_panel_keyboard(section="maint_access"),
    )
    return True


def _access_tip(*, enabled: bool, changed: bool) -> str:
    if enabled:
        return "已开启公开访问模式。" if changed else "公开访问模式已是开启状态。"
    return "已关闭公开访问模式。" if changed else "公开访问模式已是关闭状态。"


async def panel_refresh_menu(query: Any, context: Any, deps: AuditPanelDeps) -> bool:
    if deps.post_init is None:
        await query.answer("刷新功能不可用", show_alert=True)
        return True
    await query.answer("正在刷新菜单...")
    try:
        await deps.post_init(context.application)
        tip = "命令菜单刷新完成。"
    except Exception:
        tip = "命令菜单刷新失败。"
    panel = owner_panel_section_text(deps, "maint_ops")
    await query.edit_message_text(
        f"{panel}\n\n{tip}",
        parse_mode="HTML",
        reply_markup=deps.build_owner_panel_keyboard(section="maint_ops"),
    )
    return True


async def panel_export_json(query: Any, _context: Any, deps: AuditPanelDeps) -> bool:
    if deps.get_storage is None:
        await query.answer("操作不可用", show_alert=True)
        return True
    await query.answer("正在导出...")
    ok, export_file, export_name, total = await _export_json_file(deps)
    if not ok:
        await _show_backup_panel_tip(query, deps, "导出失败，请稍后重试。")
        return True
    try:
        with open(export_file, "rb") as handle:
            await query.message.reply_document(
                document=handle,
                filename=export_name,
                caption=f"导出完成，共 {total} 条订阅。",
            )
    finally:
        await _remove_file(export_file)
    await _show_backup_panel_tip(query, deps, "导出完成，文件已发送。")
    return True


async def _export_json_file(deps: AuditPanelDeps) -> tuple[bool, str, str, int]:
    store = deps.get_storage()
    return await export_subscriptions_file(store=store, admin_service=deps.admin_service)


async def _remove_file(file_path: str) -> None:
    try:
        await asyncio.get_event_loop().run_in_executor(None, os.remove, file_path)
    except OSError:
        pass


async def _show_backup_panel_tip(query: Any, deps: AuditPanelDeps, tip: str) -> None:
    panel = owner_panel_section_text(deps, "maint_backup")
    await query.edit_message_text(
        f"{panel}\n\n{tip}",
        parse_mode="HTML",
        reply_markup=deps.build_owner_panel_keyboard(section="maint_backup"),
    )


async def panel_backup_now(query: Any, _context: Any, deps: AuditPanelDeps) -> bool:
    if deps.backup_service is None:
        await query.answer("操作不可用", show_alert=True)
        return True
    await query.answer("正在生成备份...")
    zip_path, zip_name = await create_backup_file(backup_service=deps.backup_service)
    with open(zip_path, "rb") as handle:
        caption = deps.admin_service.build_backup_caption(zip_name=zip_name)
        await query.message.reply_document(
            document=handle,
            filename=zip_name,
            caption=caption,
            parse_mode="HTML",
        )
    await _show_backup_panel_tip(query, deps, "全量备份已生成并发送。")
    return True


async def panel_import_start(query: Any, context: Any, deps: AuditPanelDeps) -> bool:
    context.user_data["awaiting_import"] = True
    context.user_data.pop("awaiting_restore", None)
    await query.answer("等待上传 JSON")
    await query.edit_message_text(
        "已进入导入模式。\n请上传由导出功能生成的 JSON 文件，我会自动执行导入。",
        reply_markup=deps.inline_keyboard_markup(
            [[deps.inline_keyboard_button("返回备份页", callback_data="panel:maint_backup")]]
        ),
    )
    return True


async def panel_restore_start(query: Any, context: Any, deps: AuditPanelDeps) -> bool:
    context.user_data["awaiting_restore"] = True
    context.user_data.pop("awaiting_import", None)
    await query.answer("等待上传 ZIP")
    await query.edit_message_text(
        "已进入恢复模式。\n请上传由备份功能生成的 ZIP 文件，我会自动执行恢复。",
        reply_markup=deps.inline_keyboard_markup(
            [[deps.inline_keyboard_button("返回备份页", callback_data="panel:maint_backup")]]
        ),
    )
    return True


async def panel_listusers(query: Any, _context: Any, deps: AuditPanelDeps) -> bool:
    report = render_user_list(deps.admin_service.get_user_list_data())
    await query.edit_message_text(
        report,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=deps.inline_keyboard_markup(
            [[deps.inline_keyboard_button("返回用户页", callback_data="panel:users")]]
        ),
    )
    return True


async def panel_globallist(query: Any, _context: Any, deps: AuditPanelDeps) -> bool:
    report = render_global_list(deps.admin_service.get_globallist_data())
    await query.edit_message_text(
        report,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=deps.inline_keyboard_markup(
            [[deps.inline_keyboard_button("返回总览页", callback_data="panel:overview")]]
        ),
    )
    return True
