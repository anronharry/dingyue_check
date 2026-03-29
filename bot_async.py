"""
Telegram 订阅检测与转换机器人 - 异步版本。

本文件仅保留运行时入口、PTB 生命周期和对外暴露的 handler 变量。
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from telegram.ext import Application

import config
from app.bootstrap import build_application, log_startup_banner, register_handlers, run_polling
from app.runtime import build_handlers, create_runtime
from app.settings import AppSettings
from renderers.telegram_keyboards import build_usage_audit_keyboard

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

settings = AppSettings.from_env()
BOT_TOKEN = settings.bot_token
PROXY_PORT = settings.proxy_port
URL_CACHE_MAX_SIZE = settings.url_cache_max_size
URL_CACHE_TTL_SECONDS = settings.url_cache_ttl_seconds
ALLOWED_USER_IDS = settings.allowed_user_ids

runtime = create_runtime(
    logger=logger,
    proxy_port=PROXY_PORT,
    url_cache_max_size=URL_CACHE_MAX_SIZE,
    url_cache_ttl_seconds=URL_CACHE_TTL_SECONDS,
    allowed_user_ids=ALLOWED_USER_IDS,
)

if not ALLOWED_USER_IDS:
    logger.info("ALLOWED_USER_IDS 静态白名单为空，仅允许 Owner、动态授权用户或全员开放模式下的用户使用。")
else:
    logger.info("用户白名单已启用，当前共有 %s 个 ENV 级静态授权用户。", len(ALLOWED_USER_IDS))


async def _on_shutdown(application: Application):
    del application
    logger.info("正在关闭全局 HTTP Session 池...")
    if runtime.parser and getattr(runtime.parser, "session", None):
        await runtime.parser.session.close()
    elif runtime.shared_session:
        await runtime.shared_session.close()
    from core.geo_service import GeoLocationService

    geo_client = GeoLocationService()
    if hasattr(geo_client, "close"):
        await geo_client.close()
    logger.info("后台 HTTP Session 池清理完毕。")


async def post_init(application: Application):
    try:
        user_commands = [
            BotCommand("start", "查看使用说明与快速入口"),
            BotCommand("check", "检测我的订阅状态"),
            BotCommand("list", "查看我的订阅列表"),
            BotCommand("to_yaml", "把 TXT 节点转为 YAML"),
            BotCommand("to_txt", "把 YAML 转为 TXT"),
            BotCommand("help", "查看详细帮助"),
            BotCommand("stats", "查看我的订阅统计"),
        ]
        await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
        owner_id = int(os.getenv("OWNER_ID", 0))
        if owner_id:
            owner_commands = user_commands + [
                BotCommand("listusers", "查看授权用户列表"),
                BotCommand("allowall", "开启全员可用模式"),
                BotCommand("denyall", "关闭全员可用模式"),
                BotCommand("usageaudit", "查看最近使用记录"),
                BotCommand("checkall", "全局检测所有用户订阅"),
                BotCommand("globallist", "查看全局订阅与链接"),
                BotCommand("broadcast", "向所有用户发送通知"),
                BotCommand("backup", "导出全量备份"),
                BotCommand("restore", "从备份包恢复"),
            ]
            await application.bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=owner_id))
        if config.ENABLE_MONITOR:
            from features import monitor

            monitor.configure_monitor(application, runtime.get_storage(), runtime.get_parser, runtime.ws_manager)
        application.bot_data["build_usage_audit_keyboard"] = build_usage_audit_keyboard
        application.bot_data["admin_service"] = runtime.admin_service
        logger.info("快捷命令菜单已成功推送。")
    except Exception as exc:
        logger.error("注册快捷命令菜单失败: %s", exc)


_handlers = build_handlers(runtime, post_init=post_init)
globals().update(_handlers)
start_command = _handlers["start"]
help_command = _handlers["help"]
check_command = _handlers["check"]
checkall_command = _handlers["checkall"]
allowall_command = _handlers["allowall"]
denyall_command = _handlers["denyall"]
list_command = _handlers["list"]
stats_command = _handlers["stats"]
export_command = _handlers["export"]
import_command = _handlers["import"]
add_user_command = _handlers["adduser"]
del_user_command = _handlers["deluser"]
list_users_command = _handlers["listusers"]
usageaudit_command = _handlers["usageaudit"]
globallist_command = _handlers["globallist"]
broadcast_command = _handlers["broadcast"]
to_yaml_command = _handlers["to_yaml"]
to_txt_command = _handlers["to_txt"]
deepcheck_command = _handlers["deepcheck"]
delete_command = _handlers["delete"]
refresh_menu_command = _handlers["refresh_menu"]
backup_command = _handlers["backup"]
restore_command = _handlers["restore"]
button_callback = _handlers["button_callback"]
handle_document = _handlers["handle_document"]
handle_message = _handlers["handle_message"]

periodic_cache_cleanup = runtime.periodic_cache_cleanup
schedule_result_collapse = runtime.schedule_result_collapse


def main():
    if not BOT_TOKEN:
        logger.error("错误: 未设置 TELEGRAM_BOT_TOKEN")
        return
    log_startup_banner()
    restored, restore_note = runtime.backup_service.auto_restore_if_needed()
    logger.info("启动时 bootstrap restore: %s", restore_note if not restored else f"restored to {restore_note}")
    application = build_application(BOT_TOKEN, post_init, _on_shutdown)
    application.bot_data["build_usage_audit_keyboard"] = build_usage_audit_keyboard
    application.bot_data["admin_service"] = runtime.admin_service
    register_handlers(application, _handlers)
    if application.job_queue:
        application.job_queue.run_repeating(periodic_cache_cleanup, interval=600, first=600)
    config.print_config_summary()
    if config.OWNER_ID > 0:
        migrated = runtime.get_storage().migrate_subscriptions(config.OWNER_ID)
        if migrated:
            logger.info("历史数据迁移完成，%s 条订阅已归属到 Owner (UID: %s)。", migrated, config.OWNER_ID)
    if not config.ENABLE_MONITOR:
        logger.info("定时监控已关闭（ENABLE_MONITOR=False）。")
    run_polling(application)


if __name__ == "__main__":
    main()
