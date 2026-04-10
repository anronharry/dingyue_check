"""Application assembly helpers."""
from __future__ import annotations

import logging
from typing import Callable

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, JobQueue, MessageHandler, filters

import config
from app.constants import APP_FEATURES, APP_STARTUP, APP_TITLE

logger = logging.getLogger(__name__)


def log_startup_banner() -> None:
    logger.info("=" * 60)
    logger.info(f" {APP_TITLE} ")
    logger.info(APP_FEATURES)
    logger.info("=" * 60)
    logger.info(APP_STARTUP)

def build_application(token: str, post_init: Callable, post_shutdown: Callable) -> Application:
    jq = JobQueue()
    return Application.builder().token(token).post_init(post_init).post_shutdown(post_shutdown).job_queue(jq).build()


def register_handlers(application: Application, handlers: dict[str, Callable]) -> None:
    base_commands = [
        "start",
        "help",
        "check",
        "list",
        "stats",
        "ownerpanel",
        "to_yaml",
        "to_txt",
        "deepcheck",
        "delete",
        "refresh_menu",
    ]
    owner_ops_commands = [
        "checkall",
        "allowall",
        "denyall",
        "export",
        "import",
        "adduser",
        "deluser",
        "broadcast",
        "backup",
        "restore",
    ]
    owner_legacy_read_commands = [
        "listusers",
        "recentusers",
        "recentexports",
        "usageaudit",
        "globallist",
    ]
    command_names = base_commands + owner_ops_commands
    if config.ENABLE_OWNER_LEGACY_READ_COMMANDS:
        command_names.extend(owner_legacy_read_commands)
    for name in command_names:
        application.add_handler(CommandHandler(name, handlers[name]))
    application.add_handler(CallbackQueryHandler(handlers["button_callback"]))
    application.add_handler(MessageHandler(filters.Document.ALL, handlers["handle_document"]))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers["handle_message"]))


def run_polling(application: Application) -> None:
    application.run_polling(allowed_updates=Update.ALL_TYPES)
