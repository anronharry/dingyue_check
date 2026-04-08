"""Subscription-facing command handlers."""
from __future__ import annotations


import asyncio
import html
import time
from datetime import datetime


def make_check_command(
    *,
    is_authorized,
    send_no_permission_msg,
    get_storage,
    get_parser,
    format_traffic,
    make_sub_keyboard,
    usage_audit_service,
    logger,
):
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
                    parser_instance = await get_parser()
                    result = await parser_instance.parse(url)
                    remaining = result.get("remaining")
                    if remaining is not None and remaining <= 0:
                        raise Exception("当前订阅流量已完全耗尽（剩余 0 B）")
                    store.add_or_update(url, result)
                    res = {
                        "url": url,
                        "name": result.get("name", "未知"),
                        "remaining": remaining if remaining is not None else 0,
                        "expire_time": result.get("expire_time"),
                        "status": "success",
                    }
                except Exception as exc:
                    logger.error("检测失败 %s: %s", url, exc)
                    store.mark_check_failed(url, str(exc), operator_uid=uid, require_owner=True)
                    res = {
                        "url": url,
                        "name": data.get("name", "未知"),
                        "status": "failed",
                        "error": str(exc),
                    }

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

        try:
            await progress_msg.delete()
        except Exception:
            pass

        success_results = [r for r in results if r["status"] == "success"]
        failed_results = [r for r in results if r["status"] == "failed"]
        warning_results = []
        normal_results = []

        for item in success_results:
            remaining = item.get("remaining", 0)
            expire_time = item.get("expire_time") or ""
            is_low_traffic = remaining is not None and remaining > 0 and remaining < 5 * 1024 * 1024 * 1024
            is_expiring = False
            if expire_time:
                try:
                    expire_dt = datetime.strptime(expire_time, "%Y-%m-%d %H:%M:%S")
                    is_expiring = (expire_dt - datetime.now()).total_seconds() <= 3 * 24 * 3600
                except Exception:
                    is_expiring = False
            if is_low_traffic or is_expiring:
                warning_results.append(item)
            else:
                normal_results.append(item)

        report = (
            f"<b>📊 订阅检测结果</b>\n\n"
            f"总计: {len(results)}\n"
            f"✅ 正常: {len(normal_results)}\n"
            f"⚠️ 需关注: {len(warning_results)}\n"
            f"❌ 失效: {len(failed_results)}\n"
            + "—" * 20
            + "\n"
        )

        if warning_results:
            report += "\n<b>⚠️ 需关注的订阅</b>\n"
            for item in warning_results:
                line = f"\n<b>{html.escape(item['name'])}</b>"
                if item.get("remaining") is not None:
                    line += f"\n剩余: {format_traffic(item['remaining'])}"
                if item.get("expire_time"):
                    line += f" | 到期: {item['expire_time']}"
                line += f"\n<code>{item['url']}</code>\n"
                report += line

        if failed_results:
            report += "\n<b>❌ 已失效并自动清理</b>\n"
            for item in failed_results:
                report += (
                    f"\n<b>{html.escape(item['name'])}</b>\n"
                    f"<code>{item['url']}</code>\n"
                    f"原因：{html.escape(str(item.get('error', '未知'))[:100])}\n"
                )

        await update.message.reply_text(report, parse_mode="HTML")

        for item in success_results:
            remaining = format_traffic(item["remaining"])
            url = item["url"]
            safe_name = html.escape(item["name"])
            prefix = "⚠️" if item in warning_results else "✅"
            msg = f"<b>{prefix} {safe_name}</b>\n剩余: {remaining}"
            if item.get("expire_time"):
                msg += f" | 到期: {item['expire_time']}"
            msg += f"\n<code>{url}</code>"
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=make_sub_keyboard(url))

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
            msg = f"{label} — <b>{data['name']}</b>\n<code>{url}</code>"
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
