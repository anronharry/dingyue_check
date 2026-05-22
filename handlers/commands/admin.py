"""管理员/维护命令处理器。"""

from __future__ import annotations

import html
import os

from handlers.commands.admin_checkall import (
    make_checkall_command,
    should_auto_remove_failed_subscription as _should_auto_remove_failed_subscription,
)
from handlers.commands.admin_maintenance import (
    make_backup_command,
    make_broadcast_command,
    make_export_command,
    make_import_command,
    make_restore_command,
    make_set_public_access_command,
)
from handlers.commands.admin_utils import (
    create_backup_file,
    deliver_broadcast,
    export_subscriptions_file,
)
from renderers.messages.admin_reports import render_user_list

WEB_MIGRATION_NOTICE = (
    "低频管理视图已迁移到 Web Admin。\n"
    "请在浏览器中打开：{url}\n\n"
    "Telegram 侧保留 /checkall、/backup、/restore、/broadcast 等高频或应急命令。\n"
    "如未配置访问地址，请设置环境变量 WEB_ADMIN_PUBLIC_URL。"
)


def _web_admin_public_url() -> str:
    return os.getenv("WEB_ADMIN_PUBLIC_URL", "").strip() or "（未配置 WEB_ADMIN_PUBLIC_URL）"


def _build_web_migration_notice() -> str:
    return WEB_MIGRATION_NOTICE.format(url=_web_admin_public_url())


def make_usage_audit_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    del admin_service
    return _make_web_migration_command(
        is_owner=is_owner, owner_only_msg=owner_only_msg, schedule_auto_delete=schedule_auto_delete
    )


def make_recent_users_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    del admin_service
    return _make_web_migration_command(
        is_owner=is_owner, owner_only_msg=owner_only_msg, schedule_auto_delete=schedule_auto_delete
    )


def make_recent_exports_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    del admin_service
    return _make_web_migration_command(
        is_owner=is_owner, owner_only_msg=owner_only_msg, schedule_auto_delete=schedule_auto_delete
    )


def make_owner_panel_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    del admin_service
    return _make_web_migration_command(
        is_owner=is_owner, owner_only_msg=owner_only_msg, schedule_auto_delete=schedule_auto_delete
    )


def _make_web_migration_command(*, is_owner, owner_only_msg, schedule_auto_delete):
    async def web_migration_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        reply_msg = await update.message.reply_text(_build_web_migration_notice())
        schedule_auto_delete(context, update.message, reply_msg, delay=60)

    return web_migration_command


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
    def _build_callback(action: str, url: str, operator_uid: int) -> str:
        try:
            return get_short_callback_data(action, url, operator_uid=operator_uid)
        except TypeError:
            return get_short_callback_data(action, url)

    async def delete_command(update, context):
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return
        store = get_storage()
        if not context.args:
            await _reply_delete_usage(update, context, store, schedule_auto_delete)
            return
        await _reply_delete_confirmation(
            update,
            context,
            store,
            is_owner,
            confirm_delete_label,
            _build_callback,
            inline_keyboard_button,
            inline_keyboard_markup,
            schedule_auto_delete,
        )

    return delete_command


async def _reply_delete_usage(update, context, store, schedule_auto_delete) -> None:
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


async def _reply_delete_confirmation(
    update,
    context,
    store,
    is_owner,
    confirm_delete_label,
    build_callback,
    inline_keyboard_button,
    inline_keyboard_markup,
    schedule_auto_delete,
) -> None:
    url = context.args[0].strip()
    user_subs = (
        store.get_by_user(update.effective_user.id) if not is_owner(update) else store.get_all()
    )
    sub_data = user_subs.get(url)
    if not sub_data:
        reply_msg = await update.message.reply_text("未找到该订阅。")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)
        return
    reply_msg = await update.message.reply_text(
        _delete_confirmation_text(url, sub_data),
        parse_mode="HTML",
        reply_markup=inline_keyboard_markup(
            _delete_confirmation_keyboard(
                url, update, confirm_delete_label, build_callback, inline_keyboard_button
            )
        ),
    )
    schedule_auto_delete(context, update.message, reply_msg, delay=30)


def _delete_confirmation_text(url: str, sub_data: dict) -> str:
    return (
        f"<b>确认删除</b>\n\n"
        f"确定要删除这条订阅吗？\n"
        f"名称：<b>{html.escape(sub_data.get('name', '未命名'))}</b>\n"
        f"链接：<code>{html.escape(url)}</code>"
    )


def _delete_confirmation_keyboard(
    url, update, confirm_delete_label, build_callback, inline_keyboard_button
):
    return [
        [
            inline_keyboard_button(
                confirm_delete_label,
                callback_data=build_callback("del_confirm", url, update.effective_user.id),
            ),
            inline_keyboard_button("取消", callback_data="del_cancel"),
        ]
    ]


def make_add_user_command(*, is_owner, owner_only_msg, user_manager, schedule_auto_delete):
    async def add_user_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        uid = await _parse_user_id_arg(
            update, context, schedule_auto_delete, usage="用法：/adduser <user_id>"
        )
        if uid is None:
            return
        added = user_manager.add_user(uid)
        if added:
            reply_msg = await update.message.reply_text(
                f"已授权用户：<code>{uid}</code>", parse_mode="HTML"
            )
        else:
            reply_msg = await update.message.reply_text("该用户已在授权列表中。")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return add_user_command


def make_del_user_command(
    *, is_owner, owner_only_msg, user_manager, owner_id, schedule_auto_delete
):
    async def del_user_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        uid = await _parse_user_id_arg(
            update, context, schedule_auto_delete, usage="用法：/deluser <user_id>"
        )
        if uid is None:
            return
        if uid == owner_id:
            reply_msg = await update.message.reply_text("不能移除管理员账号。")
            schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        removed = user_manager.remove_user(uid)
        if removed:
            reply_msg = await update.message.reply_text(
                f"已移除用户：<code>{uid}</code>", parse_mode="HTML"
            )
        else:
            reply_msg = await update.message.reply_text("授权列表中不存在该用户。")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

    return del_user_command


async def _parse_user_id_arg(update, context, schedule_auto_delete, *, usage: str) -> int | None:
    if not context.args:
        reply_msg = await update.message.reply_text(usage)
        schedule_auto_delete(context, update.message, reply_msg, delay=30)
        return None
    uid_str = context.args[0]
    if not uid_str.isdigit():
        reply_msg = await update.message.reply_text("用户 ID 格式无效，只能是数字。")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)
        return None
    return int(uid_str)


def make_list_users_command(*, is_owner, owner_only_msg, admin_service, schedule_auto_delete):
    async def list_users_command(update, context):
        if not is_owner(update):
            reply_msg = await update.message.reply_text(owner_only_msg)
            schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        message = render_user_list(admin_service.get_user_list_data())
        reply_msg = await update.message.reply_text(message, parse_mode="HTML")
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
    del admin_service
    return _make_web_migration_command(
        is_owner=is_owner, owner_only_msg=owner_only_msg, schedule_auto_delete=schedule_auto_delete
    )
