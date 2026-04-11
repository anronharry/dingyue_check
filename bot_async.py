"""
Telegram subscription checker and converter (async version).

This module keeps the runtime entrypoint, PTB lifecycle hooks,
and the handler exports used by the existing project layout.
"""
from __future__ import annotations

import logging
import os
import asyncio
import signal

from aiohttp import web
from dotenv import load_dotenv
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, Update
from telegram.ext import Application

import config
from app.bootstrap import build_application, log_startup_banner, register_handlers, run_polling
from app.runtime import build_handlers, create_runtime
from app.settings import AppSettings
from renderers.telegram_keyboards import build_owner_panel_keyboard, build_recent_activity_keyboard, build_usage_audit_keyboard
from web.server import build_web_app

load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

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
    logger.info(
        "ALLOWED_USER_IDS 静态白名单为空。当前仅管理员、动态授权用户或公开访问模式用户可用。"
    )
else:
    logger.info("已启用静态白名单：环境变量中共 %s 个授权用户。", len(ALLOWED_USER_IDS))


async def _on_shutdown(application: Application):
    del application
    try:
        runtime.get_storage().flush()
    except Exception as exc:
        logger.warning("关闭时刷新订阅存储失败：%s", exc)
    runtime.user_profile_service.flush()
    logger.info("正在关闭共享 HTTP 会话池...")
    if runtime.parser and getattr(runtime.parser, "session", None):
        await runtime.parser.session.close()
    elif runtime.shared_session:
        await runtime.shared_session.close()
    from core.geo_service import GeoLocationService

    geo_client = GeoLocationService()
    if hasattr(geo_client, "close"):
        await geo_client.close()
    logger.info("HTTP 会话资源已释放。")


async def post_init(application: Application):
    try:
        user_commands = [
            BotCommand("start", "查看快速开始"),
            BotCommand("check", "检查我的订阅"),
            BotCommand("list", "查看我的订阅列表"),
            BotCommand("to_yaml", "TXT 节点转 YAML"),
            BotCommand("to_txt", "YAML 转 TXT"),
            BotCommand("help", "查看帮助"),
            BotCommand("stats", "查看我的使用统计"),
        ]
        await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
        owner_id = int(os.getenv("OWNER_ID", 0))
        if owner_id:
            owner_commands = user_commands + [
                BotCommand("ownerpanel", "Owner control panel"),
                BotCommand("refresh_menu", "Refresh command menu"),
            ]
            await application.bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=owner_id))
        if config.ENABLE_MONITOR:
            from features import monitor

            monitor.configure_monitor(application, runtime.get_storage(), runtime.get_parser, runtime.ws_manager)
        application.bot_data["build_usage_audit_keyboard"] = build_usage_audit_keyboard
        application.bot_data["build_recent_activity_keyboard"] = build_recent_activity_keyboard
        application.bot_data["build_owner_panel_keyboard"] = build_owner_panel_keyboard
        application.bot_data["admin_service"] = runtime.admin_service
        logger.info("命令菜单注册完成。")
    except Exception as exc:
        logger.error("命令菜单注册失败：%s", exc)


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
owner_panel_command = _handlers["ownerpanel"]
recent_users_command = _handlers["recentusers"]
recent_exports_command = _handlers["recentexports"]
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


def _build_application_instance() -> Application:
    application = build_application(BOT_TOKEN, post_init, _on_shutdown)
    application.bot_data["build_usage_audit_keyboard"] = build_usage_audit_keyboard
    application.bot_data["build_recent_activity_keyboard"] = build_recent_activity_keyboard
    application.bot_data["build_owner_panel_keyboard"] = build_owner_panel_keyboard
    application.bot_data["admin_service"] = runtime.admin_service
    register_handlers(application, _handlers)
    if application.job_queue:
        application.job_queue.run_repeating(periodic_cache_cleanup, interval=600, first=600)
    return application


def _log_web_security_posture() -> None:
    public_url = os.getenv("WEB_ADMIN_PUBLIC_URL", "").strip()
    if settings.web_admin_cookie_secure and public_url.startswith("http://"):
        logger.warning(
            "WEB_ADMIN_COOKIE_SECURE=true but WEB_ADMIN_PUBLIC_URL uses http:// . "
            "Use HTTPS URL or set WEB_ADMIN_COOKIE_SECURE=false only for temporary local testing."
        )
    if not settings.web_admin_cookie_secure:
        logger.warning(
            "WEB_ADMIN_COOKIE_SECURE=false. Cookies may be exposed on plain HTTP; "
            "enable HTTPS and set WEB_ADMIN_COOKIE_SECURE=true in production."
        )
    if settings.web_admin_allow_header_token:
        logger.warning(
            "WEB_ADMIN_ALLOW_HEADER_TOKEN=true. This is less strict than session-only auth; "
            "set to false unless script access is required."
        )
    if settings.web_admin_trust_proxy:
        logger.info(
            "WEB_ADMIN_TRUST_PROXY=true. Ensure service is only reachable through a trusted reverse proxy."
        )


async def _run_unified_async(application: Application) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass

    runner = None
    try:
        await application.initialize()
        await post_init(application)
        await application.start()
        if application.updater is None:
            raise RuntimeError("PTB updater unavailable; cannot start polling in unified mode.")
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Bot polling started in unified_async mode.")

        if settings.enable_web_admin:
            _log_web_security_posture()
            web_app = build_web_app(
                runtime=runtime,
                web_admin_token=settings.web_admin_token,
                web_admin_username=settings.web_admin_username,
                web_admin_session_ttl_seconds=settings.web_admin_session_ttl_seconds,
                web_admin_allow_header_token=settings.web_admin_allow_header_token,
                web_admin_cookie_secure=settings.web_admin_cookie_secure,
                web_admin_trust_proxy=settings.web_admin_trust_proxy,
                web_admin_login_window_seconds=settings.web_admin_login_window_seconds,
                web_admin_login_max_attempts=settings.web_admin_login_max_attempts,
                web_admin_redis_url=settings.web_admin_redis_url,
            )
            runner = web.AppRunner(web_app)
            await runner.setup()
            site = web.TCPSite(runner, settings.web_admin_host, settings.web_admin_port)
            await site.start()
            logger.info(
                "Web admin started at http://%s:%s/admin",
                settings.web_admin_host,
                settings.web_admin_port,
            )
        else:
            logger.info("Web admin disabled (ENABLE_WEB_ADMIN=false).")

        await stop_event.wait()
    finally:
        if application.updater and application.updater.running:
            await application.updater.stop()
        if application.running:
            await application.stop()
        await application.shutdown()
        await _on_shutdown(application)
        if runner is not None:
            await runner.cleanup()


def main():
    if not BOT_TOKEN:
        logger.error("缺少 TELEGRAM_BOT_TOKEN。")
        return
    log_startup_banner()
    restored, restore_note = runtime.backup_service.auto_restore_if_needed()
    logger.info("启动恢复结果：%s", restore_note if not restored else f"已恢复到 {restore_note}")
    application = _build_application_instance()
    config.print_config_summary()
    if config.OWNER_ID > 0:
        migrated = runtime.get_storage().migrate_subscriptions(config.OWNER_ID)
        if migrated:
            logger.info(
                "历史数据迁移完成：%s 条订阅已归属管理员（UID: %s）。",
                migrated,
                config.OWNER_ID,
            )
    if not config.ENABLE_MONITOR:
        logger.info("定时监控已关闭（ENABLE_MONITOR=False）。")
    run_mode = os.getenv("APP_RUN_MODE", "legacy_polling").strip().lower()
    if run_mode == "unified_async":
        asyncio.run(_run_unified_async(application))
        return
    run_polling(application)


if __name__ == "__main__":
    main()
