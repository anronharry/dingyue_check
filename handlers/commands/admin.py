"""管理员/维护命令处理器。"""
from __future__ import annotations

import asyncio
import html
import os
import time


async def deliver_broadcast(*, bot, user_ids, content: str, logger, title: str = "系统广播（管理员）") -> tuple[int, int]:
    """Send broadcast and return (success, failed)."""
    message_text = f"<b>{html.escape(title)}</b>\n\n{html.escape(content)}"
    success, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=message_text, parse_mode="HTML")
            success += 1
        except Exception as exc:
            failed += 1
            if logger:
                logger.warning("Broadcast send failed uid=%s error=%s", uid, exc)
    return success, failed


async def export_subscriptions_file(*, store, admin_service) -> tuple[bool, str, str, int]:
    """Export subscriptions to file and return (ok, file_path, file_name, total)."""
    export_file, export_name = admin_service.make_export_file_path()
    ok = await asyncio.get_event_loop().run_in_executor(None, store.export_to_file, export_file)
    return ok, export_file, export_name, len(store.get_all())


async def create_backup_file(*, backup_service) -> tuple[str, str]:
    """Create backup zip and return (zip_path, zip_name)."""
    return await asyncio.get_event_loop().run_in_executor(None, backup_service.create_backup)


def make_broadcast_command(*, is_owner, owner_only_msg, user_manager, schedule_auto_delete, logger):
    async def broadcast_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        if not context.args:
            reply_msg = await update.message.reply_text("用法：/broadcast <消息内容>")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        content = " ".join(context.args)
        status_msg = await update.message.reply_text("正在准备广播...")
        success, fail = await deliver_broadcast(
            bot=context.bot,
            user_ids=user_manager.get_all(),
            content=content,
            logger=logger,
        )
        final_msg = await status_msg.edit_text(f"广播完成\n成功：{success}\n失败：{fail}")
        schedule_auto_delete(context, update.message, final_msg, delay=30)

    return broadcast_command


def make_set_public_access_command(*, is_owner, owner_only_msg, access_service, enabled, schedule_auto_delete):
    async def set_public_access_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        changed, saved = access_service.set_allow_all_users(enabled)
        if not saved:
            reply_msg = await update.message.reply_text("保存公开访问状态失败，请检查数据目录权限。")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        if enabled:
            text = "已开启公开访问模式。"
            if not changed:
                text = "公开访问模式已经是开启状态。"
        else:
            text = "已关闭公开访问模式。"
            if not changed:
                text = "公开访问模式已经是关闭状态。"
        reply_msg = await update.message.reply_text(text)
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return set_public_access_command


def make_usage_audit_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    async def usage_audit_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        report, paging = admin_service.build_usage_audit_report(mode="others", page=1, page_size=5)
        reply_msg = await update.message.reply_text(
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=context.application.bot_data["build_usage_audit_keyboard"](
                mode=paging["mode"],
                page=paging["page"],
                total_pages=paging["total_pages"],
                record_count=len(paging["records"]),
            ),
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=90)

    return usage_audit_command


def make_recent_users_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    async def recent_users_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        include_owner = bool(context.args and context.args[0].lower() == "all")
        report, paging = admin_service.build_recent_users_page(include_owner=include_owner, page=1, page_size=5)
        reply_msg = await update.message.reply_text(
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=context.application.bot_data["build_recent_activity_keyboard"](
                category="users",
                scope=paging["scope"],
                page=paging["page"],
                total_pages=paging["total_pages"],
                record_count=len(paging["records"]),
            ),
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=90)

    return recent_users_command


def make_recent_exports_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    async def recent_exports_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        include_owner = bool(context.args and context.args[0].lower() == "all")
        report, paging = admin_service.build_recent_exports_page(include_owner=include_owner, page=1, page_size=5)
        reply_msg = await update.message.reply_text(
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=context.application.bot_data["build_recent_activity_keyboard"](
                category="exports",
                scope=paging["scope"],
                page=paging["page"],
                total_pages=paging["total_pages"],
                record_count=len(paging["records"]),
            ),
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=90)

    return recent_exports_command


def make_owner_panel_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    async def owner_panel_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        total_users, daily_users = admin_service.get_usage_user_counts(include_owner=False)
        panel_text = admin_service.build_owner_panel_text()
        panel_text = f"{panel_text}\n👤 使用用户: <b>{total_users}</b> | 🕒 24 小时内: <b>{daily_users}</b>"
        reply_msg = await update.message.reply_text(
            panel_text,
            parse_mode="HTML",
            reply_markup=context.application.bot_data["build_owner_panel_keyboard"](),
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=120)

    return owner_panel_command


def make_delete_command(
    *,
    is_authorized,
    send_no_permission_msg,
    get_storage,
    is_owner,
    confirm_delete_label,
    get_short_callback_data,
    inline_keyboard_button,
    inline_keyboard_markup,
    schedule_auto_delete,
):
    async def delete_command(update, context):
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return
        store = get_storage()
        if not context.args:
            subscriptions = store.get_by_user(update.effective_user.id)
            if not subscriptions:
                await update.message.reply_text("你当前没有可删除的订阅。")
                return
            reply_msg = await update.message.reply_text(
                "请先使用 /list，点击对应条目的删除按钮，\n"
                "或直接执行 <code>/delete &lt;subscription_url&gt;</code>。",
                parse_mode="HTML",
            )
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        url = context.args[0].strip()
        user_subs = store.get_by_user(update.effective_user.id) if not is_owner(update) else store.get_all()
        sub_data = user_subs.get(url)
        if not sub_data:
            reply_msg = await update.message.reply_text("未找到该订阅。")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        keyboard = [[
            inline_keyboard_button(confirm_delete_label, callback_data=get_short_callback_data("del_confirm", url)),
            inline_keyboard_button("取消", callback_data="del_cancel"),
        ]]
        reply_msg = await update.message.reply_text(
            f"<b>确认删除</b>\n\n"
            f"确定要删除这条订阅吗？\n"
            f"名称：<b>{sub_data['name']}</b>\n"
            f"链接：<code>{url}</code>",
            parse_mode="HTML",
            reply_markup=inline_keyboard_markup(keyboard),
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return delete_command


def make_export_command(*, is_owner, owner_only_msg, get_storage, schedule_auto_delete, admin_service):
    async def export_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        store = get_storage()
        export_success, export_file, export_name, total = await export_subscriptions_file(
            store=store,
            admin_service=admin_service,
        )
        if export_success:
            with open(export_file, "rb") as handle:
                await update.message.reply_document(
                    document=handle,
                    filename=export_name,
                    caption=f"导出完成，共 {total} 条订阅。",
                )
            await asyncio.get_event_loop().run_in_executor(None, os.remove, export_file)
            return
        reply_msg = await update.message.reply_text("导出失败，请稍后重试。")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return export_command


def make_import_command(*, is_owner, owner_only_msg, schedule_auto_delete):
    async def import_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        context.user_data["awaiting_import"] = True
        reply_msg = await update.message.reply_text(
            "请上传由 /export 生成的 JSON 文件，"
            "我会把内容导入到当前订阅列表中。"
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return import_command


def make_backup_command(*, is_owner, owner_only_msg, backup_service, schedule_auto_delete):
    async def backup_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        zip_path, zip_name = await create_backup_file(backup_service=backup_service)
        with open(zip_path, "rb") as handle:
            caption = context.application.bot_data["admin_service"].build_backup_caption(zip_name=zip_name)
            await update.message.reply_document(document=handle, filename=zip_name, caption=caption, parse_mode="HTML")

    return backup_command


def make_restore_command(*, is_owner, owner_only_msg, schedule_auto_delete):
    async def restore_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        context.user_data["awaiting_restore"] = True
        reply_msg = await update.message.reply_text(
            "请上传由 /backup 生成的 ZIP 备份包，"
            "我会执行完整恢复。"
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return restore_command


def make_add_user_command(*, is_owner, owner_only_msg, user_manager, schedule_auto_delete):
    async def add_user_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        if not context.args:
            reply_msg = await update.message.reply_text("用法：/adduser <user_id>")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        uid_str = context.args[0]
        if not uid_str.isdigit():
            reply_msg = await update.message.reply_text("用户 ID 格式无效，只能是数字。")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        uid = int(uid_str)
        added = user_manager.add_user(uid)
        if added:
            reply_msg = await update.message.reply_text(f"已授权用户：<code>{uid}</code>", parse_mode="HTML")
        else:
            reply_msg = await update.message.reply_text("该用户已在授权列表中。")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return add_user_command


def make_del_user_command(*, is_owner, owner_only_msg, user_manager, owner_id, schedule_auto_delete):
    async def del_user_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        if not context.args:
            reply_msg = await update.message.reply_text("用法：/deluser <user_id>")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        uid_str = context.args[0]
        if not uid_str.isdigit():
            reply_msg = await update.message.reply_text("用户 ID 格式无效，只能是数字。")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        uid = int(uid_str)
        if uid == owner_id:
            reply_msg = await update.message.reply_text("不能移除管理员账号。")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        removed = user_manager.remove_user(uid)
        if removed:
            reply_msg = await update.message.reply_text(f"已移除用户：<code>{uid}</code>", parse_mode="HTML")
        else:
            reply_msg = await update.message.reply_text("授权列表中不存在该用户。")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return del_user_command


def make_list_users_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    async def list_users_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        message = admin_service.build_user_list_message()
        reply_msg = await update.message.reply_text(
            message or "当前没有授权用户。",
            parse_mode="HTML" if message else None,
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return list_users_command


def make_refresh_menu_command(*, is_owner, post_init):
    async def refresh_menu_command(update, context):
        if not is_owner(update):
            return
        await update.message.reply_text("正在重新注册命令菜单...")
        try:
            await post_init(context.application)
            await update.message.reply_text("命令菜单刷新请求已发送。")
        except Exception as exc:
            await update.message.reply_text(f"命令菜单刷新失败：{exc}")

    return refresh_menu_command


def make_globallist_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    async def globallist_command(update, context):
        if not is_owner(update):
            await update.message.reply_text(owner_only_msg)
            return
        report = admin_service.build_globallist_report()
        if not report:
            reply_msg = await update.message.reply_text("没有其他用户的订阅数据（当前仅管理员数据）。")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        reply_msg = await update.message.reply_text(report, parse_mode="HTML")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return globallist_command


def make_checkall_command(
    *,
    is_owner,
    owner_only_msg,
    get_storage,
    get_parser,
    make_sub_keyboard,
    admin_service,
    usage_audit_service,
    schedule_auto_delete,
    subscription_check_service=None,
):
    async def checkall_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        store = get_storage()
        subscriptions = store.get_all()
        if not subscriptions:
            reply_msg = await update.message.reply_text("没有可检查的订阅记录。")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        usage_audit_service.log_check(user=update.effective_user, urls=list(subscriptions.keys()), source="/checkall")
        progress_msg = await update.message.reply_text(
            "<b>正在检查全部用户订阅...</b>\n请稍候...",
            parse_mode="HTML",
        )
        schedule_auto_delete(context, update.message, progress_msg, delay=30)
        semaphore = asyncio.Semaphore(20)
        total_count = len(subscriptions)
        completed_count = 0
        last_update_time = time.time()

        async def check_one_global(url, data):
            nonlocal completed_count, last_update_time
            async with semaphore:
                try:
                    original_owner = data.get("owner_uid", 0)
                    if subscription_check_service:
                        result = await subscription_check_service.parse_and_store(
                            url=url,
                            owner_uid=original_owner,
                        )
                    else:
                        parser_instance = await get_parser()
                        result = await parser_instance.parse(url)
                        store.add_or_update(url, result, user_id=original_owner)
                    if result.get("remaining", 1) <= 0:
                        raise Exception("流量已耗尽")
                    res = {
                        "url": url,
                        "name": result.get("name", "未知"),
                        "owner_uid": original_owner,
                        "status": "success",
                    }
                except Exception as exc:
                    store.mark_check_failed(url, str(exc))
                    res = {
                        "url": url,
                        "name": data.get("name", "未知"),
                        "owner_uid": data.get("owner_uid", 0),
                        "status": "failed",
                        "error": str(exc),
                    }
                completed_count += 1
                current_time = time.time()
                if current_time - last_update_time > 2.0 or completed_count == total_count:
                    try:
                        await progress_msg.edit_text(f"正在检查全部用户订阅：{completed_count} / {total_count} ...")
                        last_update_time = current_time
                    except Exception:
                        pass
                return res

        store.begin_batch()
        results = await asyncio.gather(*[check_one_global(url, data) for url, data in subscriptions.items()])
        store.end_batch(save=True)
        try:
            await progress_msg.delete()
        except Exception:
            pass
        report_msg = await update.message.reply_text(
            admin_service.build_checkall_report(results=results, viewer_uid=update.effective_user.id),
            parse_mode="HTML",
        )
        schedule_auto_delete(context, update.message, report_msg, delay=60)

    return checkall_command
