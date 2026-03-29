"""Owner/admin and maintenance command handlers."""
from __future__ import annotations

import asyncio
import os
import time


def make_broadcast_command(*, is_owner, owner_only_msg, user_manager, schedule_auto_delete, logger):
    async def broadcast_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        if not context.args:
            reply_msg = await update.message.reply_text("用法：/broadcast <通知内容>")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        content = " ".join(context.args)
        broadcast_msg = f"📢 <b>系统通知（来自 Owner）</b>\n\n{content}"
        status_msg = await update.message.reply_text("📡 正在准备发送广播...")
        success, fail = 0, 0
        for uid in user_manager.get_all():
            try:
                await context.bot.send_message(chat_id=uid, text=broadcast_msg, parse_mode="HTML")
                success += 1
            except Exception as exc:
                logger.warning("广播发送失败 UID:%s: %s", uid, exc)
                fail += 1
        final_msg = await status_msg.edit_text(f"✅ 广播发送完成\n成功：{success}\n失败：{fail}")
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
            reply_msg = await update.message.reply_text("❌ 状态保存失败，请检查磁盘权限或数据目录。")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        if enabled:
            text = "✅ 已开启全员可用模式。"
            if not changed:
                text = "ℹ️ 全员可用模式已经是开启状态。"
        else:
            text = "✅ 已关闭全员可用模式。"
            if not changed:
                text = "ℹ️ 全员可用模式已经是关闭状态。"
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
        reply_msg = await update.message.reply_text(
            admin_service.build_owner_panel_text(),
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
                await update.message.reply_text("📭 您没有订阅可删除")
                return
            reply_msg = await update.message.reply_text(
                "📋 请使用 /list 查看订阅列表，点击每条下方的删除按钮直接操作\n"
                "或使用: <code>/delete &lt;订阅链接&gt;</code>",
                parse_mode="HTML",
            )
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        url = context.args[0].strip()
        user_subs = store.get_by_user(update.effective_user.id) if not is_owner(update) else store.get_all()
        sub_data = user_subs.get(url)
        if not sub_data:
            reply_msg = await update.message.reply_text("❌ 未找到该订阅")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        keyboard = [[
            inline_keyboard_button(confirm_delete_label, callback_data=get_short_callback_data("del_confirm", url)),
            inline_keyboard_button("❌ 取消", callback_data="del_cancel"),
        ]]
        reply_msg = await update.message.reply_text(
            f"⚠️ <b>删除确认</b>\n\n确定要删除以下订阅吗？\n名称：<b>{sub_data['name']}</b>\n链接：<code>{url}</code>",
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
        export_file, export_name = admin_service.make_export_file_path()
        export_success = await asyncio.get_event_loop().run_in_executor(None, store.export_to_file, export_file)
        if export_success:
            with open(export_file, "rb") as handle:
                await update.message.reply_document(document=handle, filename=export_name, caption=f"✅ 已导出 {len(store.get_all())} 个订阅")
            await asyncio.get_event_loop().run_in_executor(None, os.remove, export_file)
            return
        reply_msg = await update.message.reply_text("❌ 导出失败，请稍后重试")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return export_command


def make_import_command(*, is_owner, owner_only_msg, schedule_auto_delete):
    async def import_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        context.user_data["awaiting_import"] = True
        reply_msg = await update.message.reply_text("请上传由 /export 导出的 JSON 文件，我会自动导入到当前订阅列表。")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return import_command


def make_backup_command(*, is_owner, owner_only_msg, backup_service, schedule_auto_delete):
    async def backup_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        zip_path, zip_name = backup_service.create_backup()
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
        reply_msg = await update.message.reply_text("请上传由 /backup 导出的 ZIP 备份包，我会执行全量恢复。")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return restore_command


def make_add_user_command(*, is_owner, owner_only_msg, user_manager, schedule_auto_delete):
    async def add_user_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        if not context.args:
            reply_msg = await update.message.reply_text("用法：/adduser <用户ID>")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        uid_str = context.args[0]
        if not uid_str.isdigit():
            reply_msg = await update.message.reply_text("❌ 用户 ID 格式无效")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        uid = int(uid_str)
        reply_msg = await update.message.reply_text(
            f"✅ 已授权用户：<code>{uid}</code>" if user_manager.add_user(uid) else "ℹ️ 该用户已在授权名单中",
            parse_mode="HTML" if user_manager.is_authorized(uid) else None,
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return add_user_command


def make_del_user_command(*, is_owner, owner_only_msg, user_manager, owner_id, schedule_auto_delete):
    async def del_user_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        if not context.args:
            reply_msg = await update.message.reply_text("用法：/deluser <用户ID>")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        uid_str = context.args[0]
        if not uid_str.isdigit():
            reply_msg = await update.message.reply_text("❌ 用户 ID 格式无效")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        uid = int(uid_str)
        if uid == owner_id:
            reply_msg = await update.message.reply_text("❌ 无法移除 Owner 自身")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        reply_msg = await update.message.reply_text(
            f"✅ 已移除授权用户：<code>{uid}</code>" if user_manager.remove_user(uid) else "❌ 名单中未找到该用户",
            parse_mode="HTML" if uid_str.isdigit() else None,
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return del_user_command


def make_list_users_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    async def list_users_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        message = admin_service.build_user_list_message()
        reply_msg = await update.message.reply_text(message or "📭 当前无授权用户", parse_mode="HTML" if message else None)
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return list_users_command


def make_refresh_menu_command(*, is_owner, post_init):
    async def refresh_menu_command(update, context):
        if not is_owner(update):
            return
        await update.message.reply_text("⏳ 正在尝试重新推送快捷菜单...")
        try:
            await post_init(context.application)
            await update.message.reply_text("✅ 菜单重新注册请求已发送。")
        except Exception as exc:
            await update.message.reply_text(f"❌ 菜单注册失败：{exc}")

    return refresh_menu_command


def make_globallist_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    async def globallist_command(update, context):
        if not is_owner(update):
            await update.message.reply_text(owner_only_msg)
            return
        report = admin_service.build_globallist_report()
        if not report:
            reply_msg = await update.message.reply_text("✨ 当前除了 Owner 外暂无其他用户的订阅")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        reply_msg = await update.message.reply_text(report, parse_mode="HTML")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return globallist_command


def make_checkall_command(*, is_owner, owner_only_msg, get_storage, get_parser, make_sub_keyboard, admin_service, usage_audit_service, schedule_auto_delete):
    async def checkall_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        store = get_storage()
        subscriptions = store.get_all()
        if not subscriptions:
            reply_msg = await update.message.reply_text("📭 暂无任何订阅记录")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        usage_audit_service.log_check(user=update.effective_user, urls=list(subscriptions.keys()), source="/checkall")
        progress_msg = await update.message.reply_text("🌍 <b>正在检测所有用户的订阅</b>\n请稍候...", parse_mode="HTML")
        schedule_auto_delete(context, update.message, progress_msg, delay=30)
        semaphore = asyncio.Semaphore(20)
        total_count = len(subscriptions)
        completed_count = 0
        last_update_time = time.time()

        async def check_one_global(url, data):
            nonlocal completed_count, last_update_time
            async with semaphore:
                try:
                    parser_instance = await get_parser()
                    result = await parser_instance.parse(url)
                    if result.get("remaining", 1) <= 0:
                        raise Exception("流量已耗尽")
                    original_owner = data.get("owner_uid", 0)
                    store.add_or_update(url, result, user_id=original_owner)
                    res = {"url": url, "name": result.get("name", "未知"), "owner_uid": original_owner, "status": "success"}
                except Exception as exc:
                    store.remove(url)
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
                        await progress_msg.edit_text(f"⏳ 正在检测所有用户的订阅：{completed_count} / {total_count} 已完成...")
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
