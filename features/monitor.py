"""
后台定时监控与告警模块
负责定期检测所有订阅状态并向用户推送告警
"""

import asyncio
import logging
from datetime import datetime
from typing import Callable, Set

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

logger = logging.getLogger(__name__)

# 全局定时器实例
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


async def check_subscriptions_job(
    app: Application,
    storage,                   # SubscriptionStorage 类型（避免循环导入，使用鸭子类型）
    get_parser_fn: Callable,   # 注入 bot_async.get_parser() 函数，打破循环依赖
    allowed_user_ids: Set[int]
):
    """
    后台定时任务：检查所有订阅状态
    发现流量告急或即将到期时，推送告警给白名单内所有用户
    """
    from utils.utils import format_traffic  # 局部导入，避免顶层循环引用风险

    logger.info("⏰ 开始执行定时巡检任务...")
    subs = storage.get_all()
    if not subs:
        logger.info("无订阅记录，跳过本次巡检。")
        return

    parser = get_parser_fn()
    alerts = []

    for url, data in subs.items():
        try:
            # 在线程池中同步解析，不阻塞事件循环
            result = await asyncio.get_running_loop().run_in_executor(
                None, parser.parse, url
            )
            storage.add_or_update(url, result)

            name = result.get('name', '未知')
            total = result.get('total', 0)
            remaining = result.get('remaining', 0)
            expire_str = result.get('expire_time')

            traffic_alert = False
            if total > 0 and remaining is not None:
                ratio = remaining / total
                # 剩余不足 10% 或绝对值小于 5 GB
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
                msg = f"⚠️ <b>订阅异常告警</b> ⚠️\n名称: <b>{name}</b>\n"
                if traffic_alert:
                    msg += (
                        f"❗️ 剩余流量告急: 仅剩 {format_traffic(remaining)}"
                        f" (总计 {format_traffic(total)})\n"
                    )
                if time_alert:
                    msg += f"⏳ 即将到期: {expire_str} (≤3天)\n"
                alerts.append(msg)

        except Exception as e:
            logger.error(f"定时检测出错 {url}: {e}")

    if alerts and allowed_user_ids:
        combined_message = "\n\n".join(alerts)
        for user_id in allowed_user_ids:
            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=combined_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"推送告警失败 user_id={user_id}: {e}")

    logger.info(f"✅ 巡检完成，共发现 {len(alerts)} 条告警。")


def start_monitor(app: Application, storage, get_parser_fn: Callable, allowed_user_ids: Set[int]):
    """
    配置并注册后台监控定时任务到 Application 的生命周期中。

    Args:
        app: Telegram Application 实例
        storage: SubscriptionStorage 实例
        get_parser_fn: 获取解析器的工厂函数（用于打破循环导入）
        allowed_user_ids: 告警推送的用户 ID 集合
    """
    async def _post_init(application: Application):
        scheduler.add_job(
            check_subscriptions_job,
            'cron',
            hour='12,20',
            minute=0,
            args=[application, storage, get_parser_fn, allowed_user_ids],
            id='sub_monitor',
            replace_existing=True
        )
        scheduler.start()
        logger.info("✅ 智能定时监控已启动 (每天 12:00 / 20:00 自动巡检)")

    # 将启动逻辑挂载到 ptb 的 post_init 回调中，确保此时 Event Loop 已就绪
    if app.post_init:
        # 如果已经存在 post_init 回调，我们需要组合它们
        pass # 此处从简，bot_async.py 中并未使用 post_init，因此直接覆写即可
    app.post_init = _post_init
