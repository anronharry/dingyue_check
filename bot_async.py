"""
Telegram subscription checker and converter (async version).

This module keeps the runtime entrypoint, PTB lifecycle hooks,
and the handler exports used by the existing project layout.
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from telegram.ext import Application

import config
from app.bootstrap import build_application, log_startup_banner, register_handlers, run_polling
from app.runtime import build_handlers, create_runtime
from app.settings import AppSettings
from renderers.telegram_keyboards import build_owner_panel_keyboard, build_recent_activity_keyboard, build_usage_audit_keyboard

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
    logger.info(
        "ALLOWED_USER_IDS static whitelist is empty. Access is limited to Owner, dynamically authorized users, "
        "or users when public mode is enabled."
    )
else:
    logger.info("Whitelist enabled: %s statically authorized users from environment.", len(ALLOWED_USER_IDS))


async def _on_shutdown(application: Application):
    del application
    try:
        runtime.get_storage().flush()
    except Exception as exc:
        logger.warning("Failed to flush subscriptions on shutdown: %s", exc)
    runtime.user_profile_service.flush()
    logger.info("Closing shared HTTP session pool...")
    if runtime.parser and getattr(runtime.parser, "session", None):
        await runtime.parser.session.close()
    elif runtime.shared_session:
        await runtime.shared_session.close()
    from core.geo_service import GeoLocationService

    geo_client = GeoLocationService()
    if hasattr(geo_client, "close"):
        await geo_client.close()
    logger.info("HTTP session resources released.")


async def post_init(application: Application):
    try:
        user_commands = [
            BotCommand("start", "Show quick start guide"),
            BotCommand("check", "Check my subscriptions"),
            BotCommand("list", "List my subscriptions"),
            BotCommand("to_yaml", "Convert TXT nodes to YAML"),
            BotCommand("to_txt", "Convert YAML to TXT"),
            BotCommand("help", "Show help message"),
            BotCommand("stats", "Show my usage stats"),
        ]
        await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
        owner_id = int(os.getenv("OWNER_ID", 0))
        if owner_id:
            owner_commands = user_commands + [
                BotCommand("listusers", "List authorized users"),
                BotCommand("ownerpanel", "Open owner control panel"),
                BotCommand("recentusers", "Show recent active users"),
                BotCommand("recentexports", "Show recent export logs"),
                BotCommand("allowall", "Enable public access mode"),
                BotCommand("denyall", "Disable public access mode"),
                BotCommand("usageaudit", "Show recent usage logs"),
                BotCommand("checkall", "Check all user subscriptions"),
                BotCommand("globallist", "List global subscriptions"),
                BotCommand("broadcast", "Send a broadcast message"),
                BotCommand("backup", "Export full backup"),
                BotCommand("restore", "Restore from backup package"),
            ]
            await application.bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=owner_id))
        if config.ENABLE_MONITOR:
            from features import monitor

            monitor.configure_monitor(application, runtime.get_storage(), runtime.get_parser, runtime.ws_manager)
        application.bot_data["build_usage_audit_keyboard"] = build_usage_audit_keyboard
        application.bot_data["build_recent_activity_keyboard"] = build_recent_activity_keyboard
        application.bot_data["build_owner_panel_keyboard"] = build_owner_panel_keyboard
        application.bot_data["admin_service"] = runtime.admin_service
        logger.info("Command menu registration completed.")
    except Exception as exc:
        logger.error("Failed to register command menu: %s", exc)


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


def main():
    if not BOT_TOKEN:
        logger.error("Missing TELEGRAM_BOT_TOKEN.")
        return
    log_startup_banner()
    restored, restore_note = runtime.backup_service.auto_restore_if_needed()
    logger.info("Startup bootstrap restore: %s", restore_note if not restored else f"restored to {restore_note}")
    application = build_application(BOT_TOKEN, post_init, _on_shutdown)
    application.bot_data["build_usage_audit_keyboard"] = build_usage_audit_keyboard
    application.bot_data["build_recent_activity_keyboard"] = build_recent_activity_keyboard
    application.bot_data["build_owner_panel_keyboard"] = build_owner_panel_keyboard
    application.bot_data["admin_service"] = runtime.admin_service
    register_handlers(application, _handlers)
    if application.job_queue:
        application.job_queue.run_repeating(periodic_cache_cleanup, interval=600, first=600)
    config.print_config_summary()
    if config.OWNER_ID > 0:
        migrated = runtime.get_storage().migrate_subscriptions(config.OWNER_ID)
        if migrated:
            logger.info(
                "Historical data migration completed: %s subscriptions now belong to Owner (UID: %s).",
                migrated,
                config.OWNER_ID,
            )
    if not config.ENABLE_MONITOR:
        logger.info("Scheduled monitor disabled (ENABLE_MONITOR=False).")
    run_polling(application)


if __name__ == "__main__":
    main()
