"""Application assembly helpers."""
from __future__ import annotations

import logging
from typing import Callable

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, JobQueue, MessageHandler, filters

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
    command_names = [
        "start",
        "help",
        "check",
        "checkall",
        "allowall",
        "denyall",
        "list",
        "stats",
        "export",
        "import",
        "adduser",
        "deluser",
        "listusers",
        "ownerpanel",
        "recentusers",
        "recentexports",
        "usageaudit",
        "globallist",
        "broadcast",
        "to_yaml",
        "to_txt",
        "deepcheck",
        "delete",
        "refresh_menu",
        "backup",
        "restore",
    ]
    for name in command_names:
        application.add_handler(CommandHandler(name, handlers[name]))
    application.add_handler(CallbackQueryHandler(handlers["button_callback"]))
    application.add_handler(MessageHandler(filters.Document.ALL, handlers["handle_document"]))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers["handle_message"]))


def run_polling(application: Application) -> None:
    application.run_polling(allowed_updates=Update.ALL_TYPES)
