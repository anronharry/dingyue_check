"""Basic user command handlers built from injected dependencies."""
from __future__ import annotations

from services.report_service import build_help_message, build_start_message, build_stats_message


def make_start_command(*, is_authorized, is_owner, send_no_permission_msg, logger):
    async def start_command(update, context):
        if not is_authorized(update):
            logger.warning("未授权访问 /start，用户 ID: %s", update.effective_user.id)
            await send_no_permission_msg(update)
            return
        await update.message.reply_text(build_start_message(owner_mode=is_owner(update)), parse_mode="HTML")

    return start_command


def make_help_command(*, is_authorized, is_owner, send_no_permission_msg, schedule_auto_delete):
    async def help_command(update, context):
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return
        reply_msg = await update.message.reply_text(
            build_help_message(owner_mode=is_owner(update)),
            parse_mode="HTML",
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return help_command


def make_stats_command(
    *,
    is_authorized,
    is_owner,
    send_no_permission_msg,
    get_storage,
    schedule_auto_delete,
):
    async def stats_command(update, context):
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return
        store = get_storage()
        uid = update.effective_user.id
        stats = store.get_user_statistics(uid)
        reply_msg = await update.message.reply_text(
            build_stats_message(stats=stats, owner_mode=is_owner(update)),
            parse_mode="HTML",
        )
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return stats_command
