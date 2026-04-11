"""Subscription-facing command handlers."""
from __future__ import annotations

import asyncio
import html
import time

from core.models import BatchCheckResult, SubscriptionEntity
from renderers.messages.admin_reports import render_subscription_check_report


def make_check_command(
    *,
    is_authorized,
    is_owner,
    send_no_permission_msg,
    get_storage,
    get_parser,
    format_traffic,
    make_sub_keyboard,
    usage_audit_service,
    logger,
    subscription_check_service=None,
):
    del is_owner, make_sub_keyboard

    async def check_command(update, context):
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return

        store = get_storage()
        uid = update.effective_user.id
        tag = context.args[0] if context.args else None

        if tag:
            user_subs = store.get_by_user(uid)
            subscriptions = {url: data for url, data in user_subs.items() if tag in data.get("tags", [])}
            if not subscriptions:
                await update.message.reply_text(f"📭 标签 '{tag}' 下没有订阅")
                return
            msg_text = f"🔍 正在检测标签 '{tag}' 下的订阅（共 {len(subscriptions)} 个）..."
        else:
            subscriptions = store.get_by_user(uid)
            if not subscriptions:
                await update.message.reply_text("📭 暂无订阅记录，请先发送订阅链接。")
                return
            msg_text = f"🔍 正在检测您的订阅（共 {len(subscriptions)} 个）..."

        usage_audit_service.log_check(
            user=update.effective_user,
            urls=list(subscriptions.keys()),
            source="/check",
        )

        progress_msg = await update.message.reply_text(msg_text)
        semaphore = asyncio.Semaphore(20)
        total_count = len(subscriptions)
        completed_count = 0
        last_update_time = time.time()

        async def check_one(url, data):
            nonlocal completed_count, last_update_time
            async with semaphore:
                try:
                    if subscription_check_service:
                        result = await subscription_check_service.parse_and_store(
                            url=url,
                            owner_uid=data.get("owner_uid", uid),
                        )
                    else:
                        parser_instance = await get_parser()
                        result = await parser_instance.parse(url)
                        store.add_or_update(url, result)

                    remaining = result.get("remaining")
                    if remaining is not None and remaining <= 0:
                        raise Exception("当前订阅流量已完全耗尽（剩余 0 B）")
                    res = SubscriptionEntity.from_parse_result(
                        url=url,
                        result=result,
                        owner_uid=data.get("owner_uid", uid),
                    )
                except Exception as exc:
                    logger.error("检测失败 %s: %s", url, exc)
                    store.mark_check_failed(url, str(exc), operator_uid=uid, require_owner=True)
                    res = SubscriptionEntity.from_failure(
                        url=url,
                        name=data.get("name", "未知"),
                        error=str(exc),
                        owner_uid=data.get("owner_uid", uid),
                    )

                completed_count += 1
                current_time = time.time()
                if current_time - last_update_time > 2.0 or completed_count == total_count:
                    try:
                        await progress_msg.edit_text(f"⏳ 正在检测: {completed_count} / {total_count} 完成...")
                        last_update_time = current_time
                    except Exception:
                        pass
                return res

        store.begin_batch()
        results = await asyncio.gather(*[check_one(url, data) for url, data in subscriptions.items()])
        store.end_batch(save=True)

        batch = BatchCheckResult(entries=results)
        final_report = render_subscription_check_report(batch=batch, format_traffic=format_traffic)
        try:
            await progress_msg.edit_text(final_report, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(final_report, parse_mode="HTML")

    return check_command


def make_list_command(
    *,
    is_authorized,
    send_no_permission_msg,
    get_storage,
    get_short_callback_data,
    button_labels,
    telegram_inline_button,
    telegram_inline_markup,
    schedule_auto_delete,
):
    async def list_command(update, context):
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return

        store = get_storage()
        uid = update.effective_user.id
        subscriptions = store.get_by_user(uid)
        if not subscriptions:
            await update.message.reply_text("📭 您没有订阅，请先发送订阅链接。")
            return

        tags = sorted({t for data in subscriptions.values() for t in data.get("tags", [])})
        untagged = {url: data for url, data in subscriptions.items() if not data.get("tags")}
        header = f"<b>📋 我的订阅列表 (共 {len(subscriptions)} 个)</b>"
        reply_msg = await update.message.reply_text(header, parse_mode="HTML")
        schedule_auto_delete(context, update.message, reply_msg, delay=30)

        async def send_sub_item(url, data, tag_label=""):
            label = f"{tag_label}" if tag_label else "📦 未分组"
            msg = f"{label} — <b>{html.escape(data.get('name', '未命名'))}</b>\n<code>{html.escape(url)}</code>"
            keyboard = [[
                telegram_inline_button(button_labels["recheck"], callback_data=get_short_callback_data("recheck", url)),
                telegram_inline_button(button_labels["tag"], callback_data=get_short_callback_data("tag", url)),
                telegram_inline_button(button_labels["delete"], callback_data=get_short_callback_data("delete", url)),
            ]]
            await update.message.reply_text(
                msg,
                parse_mode="HTML",
                reply_markup=telegram_inline_markup(keyboard),
            )

        for tag in tags:
            tagged_subs = {url: data for url, data in subscriptions.items() if tag in data.get("tags", [])}
            for url, data in tagged_subs.items():
                await send_sub_item(url, data, tag_label=f"🏷️ {tag}")

        for url, data in untagged.items():
            await send_sub_item(url, data)

    return list_command
