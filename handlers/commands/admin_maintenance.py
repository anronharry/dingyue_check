"""Small owner maintenance command handlers."""

from __future__ import annotations

from typing import Any

from handlers.commands.admin_utils import (
    create_backup_file,
    deliver_broadcast,
    export_subscriptions_file,
    remove_file_async,
)


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


def make_set_public_access_command(
    *, is_owner, owner_only_msg, access_service, enabled, schedule_auto_delete
):
    async def set_public_access_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        changed, saved = access_service.set_allow_all_users(enabled)
        if not saved:
            reply_msg = await update.message.reply_text(
                "保存公开访问状态失败，请检查数据目录权限。"
            )
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        reply_msg = await update.message.reply_text(
            _public_access_text(enabled=enabled, changed=changed)
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return set_public_access_command


def _public_access_text(*, enabled: bool, changed: bool) -> str:
    if enabled:
        return "已开启公开访问模式。" if changed else "公开访问模式已经是开启状态。"
    return "已关闭公开访问模式。" if changed else "公开访问模式已经是关闭状态。"


def make_export_command(
    *, is_owner, owner_only_msg, get_storage, schedule_auto_delete, admin_service
):
    async def export_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        export_success, export_file, export_name, total = await export_subscriptions_file(
            store=get_storage(),
            admin_service=admin_service,
        )
        if export_success:
            with open(export_file, "rb") as handle:
                await update.message.reply_document(
                    document=handle,
                    filename=export_name,
                    caption=f"导出完成，共 {total} 条订阅。",
                )
            await remove_file_async(export_file)
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
            "请上传由 /export 生成的 JSON 文件，我会把内容导入到当前订阅列表中。"
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
            caption = context.application.bot_data["admin_service"].build_backup_caption(
                zip_name=zip_name
            )
            await update.message.reply_document(
                document=handle, filename=zip_name, caption=caption, parse_mode="HTML"
            )

    return backup_command


def make_restore_command(*, is_owner, owner_only_msg, schedule_auto_delete):
    async def restore_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        context.user_data["awaiting_restore"] = True
        reply_msg = await update.message.reply_text(
            "请上传由 /backup 生成的 ZIP 备份包，我会执行完整恢复。"
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return restore_command
