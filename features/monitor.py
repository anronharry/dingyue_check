"""后台定时巡检与预警模块。"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


async def check_subscriptions_job(
    app: Application,
    storage,
    get_parser_fn: Callable,
    ws_manager=None,
    alert_preference_service=None,
):
    """定时检查所有订阅，并按 owner 分组发送预警。"""
    from utils.utils import format_traffic

    logger.info("开始执行定时巡检任务...")
    if ws_manager:
        ws_manager.cleanup_temp(max_age_hours=24)

    subs = storage.get_all()
    if not subs:
        logger.info("无订阅记录，跳过本次巡检。")
        return

    parser = await get_parser_fn()
    alerts_by_user: dict[int, list[str]] = defaultdict(list)

    for url, data in subs.items():
        owner_uid = data.get("owner_uid", 0)
        if not owner_uid:
            continue

        try:
            result = await parser.parse(url)
            storage.add_or_update(url, result, user_id=owner_uid)

            name = result.get("name", "未知")
            total = result.get("total", 0)
            remaining = result.get("remaining", 0)
            expire_str = result.get("expire_time")

            traffic_alert = False
            if total > 0 and remaining is not None:
                ratio = remaining / total
                if ratio < 0.10 or remaining < 5 * 1024 * 1024 * 1024:
                    traffic_alert = True

            time_alert = False
            if expire_str:
                try:
                    expire_time = datetime.strptime(expire_str, "%Y-%m-%d %H:%M:%S")
                    days_left = (expire_time - datetime.now()).days
                    if 0 <= days_left <= 3:
                        time_alert = True
                except Exception:
                    pass

            if traffic_alert or time_alert:
                msg = f"⚠️ <b>订阅预警</b>\n<b>{name}</b>\n"
                if traffic_alert:
                    msg += f"剩余: {format_traffic(remaining)} / 总量: {format_traffic(total)}\n"
                if time_alert:
                    msg += f"到期：{expire_str}（3 天内）\n"
                msg += f"链接：<code>{url}</code>"
                alerts_by_user[owner_uid].append(msg)
        except Exception as exc:
            logger.error("定时巡检失败 %s: %s", url, exc)

    total_alerts = sum(len(items) for items in alerts_by_user.values())
    mute_keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔕 关闭预警提醒", callback_data="mute_alerts:off")]]
    )
    pushed_users = 0
    for user_id, messages in alerts_by_user.items():
        if alert_preference_service and alert_preference_service.is_muted(user_id):
            continue
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text="\n\n".join(messages),
                parse_mode="HTML",
                reply_markup=mute_keyboard,
            )
            pushed_users += 1
        except Exception as exc:
            logger.error("推送预警失败 user_id=%s: %s", user_id, exc)

    logger.info("巡检完成，共发现 %s 条预警，涉及 %s 个用户，成功推送 %s 个用户。", total_alerts, len(alerts_by_user), pushed_users)


def configure_monitor(
    app: Application,
    storage,
    get_parser_fn: Callable,
    ws_manager=None,
    alert_preference_service=None,
):
    """向调度器注册巡检任务，不覆盖 Application.post_init。"""
    scheduler.add_job(
        check_subscriptions_job,
        "cron",
        hour="12,20",
        minute=0,
        args=[app, storage, get_parser_fn, ws_manager, alert_preference_service],
        id="sub_monitor",
        replace_existing=True,
    )
    if not scheduler.running:
        scheduler.start()
    logger.info("自动巡检与预警已启动（每天 12:00 / 20:00 执行）。")
