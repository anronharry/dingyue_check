"""Runtime container and handler assembly helpers."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from app.constants import BTN_CONFIRM_DELETE, BTN_DELETE, BTN_RECHECK, BTN_TAG, OWNER_ONLY_MSG, TAG_EXISTS_ALERT, TAG_FORBIDDEN_MSG
from core.access_control import UserManager
from core.access_state import AccessStateStore
from core.node_tester import _async_run_node_latency_test
from core.parser import SubscriptionParser
from core.storage_enhanced import SubscriptionStorage
from core.workspace_manager import WorkspaceManager
from features import latency_tester
from handlers.callbacks.router import make_button_callback
from handlers.callbacks.subscription_actions import make_subscription_callback_handler
from handlers.commands.admin import (
    make_add_user_command,
    make_backup_command,
    make_broadcast_command,
    make_checkall_command,
    make_del_user_command,
    make_delete_command,
    make_export_command,
    make_globallist_command,
    make_import_command,
    make_list_users_command,
    make_refresh_menu_command,
    make_restore_command,
    make_set_public_access_command,
    make_usage_audit_command,
)
from handlers.commands.basic import make_help_command, make_start_command, make_stats_command
from handlers.commands.conversion import make_deepcheck_command, make_to_txt_command, make_to_yaml_command
from handlers.commands.subscriptions import make_check_command, make_list_command
from handlers.messages.documents import make_document_handler, make_node_text_handler
from handlers.messages.router import make_message_handler
from handlers.messages.subscriptions import make_subscription_handler
from jobs.cache_cleanup_job import run_cache_cleanup
from renderers.formatters import format_subscription_compact, format_subscription_info
from renderers.telegram_keyboards import build_subscription_keyboard, build_usage_audit_keyboard
from services.access_service import AccessService
from services.admin_service import AdminService
from services.backup_service import BackupService
from services.conversion_service import ConversionService
from services.document_service import DocumentService
from services.export_cache_service import ExportCacheService
from services.usage_audit_service import UsageAuditService
from services.user_profile_service import UserProfileService
from utils.utils import InputDetector, format_traffic, is_valid_url


@dataclass
class Runtime:
    logger: logging.Logger
    proxy_port: int
    url_cache_max_size: int
    url_cache_ttl_seconds: int
    allowed_user_ids: set[int]
    ws_manager: WorkspaceManager
    access_state_store: AccessStateStore
    usage_audit_service: UsageAuditService
    user_profile_service: UserProfileService
    export_cache_service: ExportCacheService
    backup_service: BackupService
    user_manager: UserManager
    access_service: AccessService
    admin_service: AdminService
    conversion_service: ConversionService
    document_service: DocumentService
    parser: SubscriptionParser | None = None
    storage: SubscriptionStorage | None = None
    shared_session: object | None = None
    url_cache: OrderedDict | None = None

    def __post_init__(self):
        if self.url_cache is None:
            self.url_cache = OrderedDict()

    def get_storage(self):
        if self.storage is None:
            self.storage = SubscriptionStorage()
        return self.storage

    async def get_parser(self):
        if self.shared_session is None:
            import aiohttp

            self.shared_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=100, limit_per_host=20))
        if self.parser is None:
            self.parser = SubscriptionParser(proxy_port=self.proxy_port, use_proxy=False, session=self.shared_session)
        return self.parser

    def make_sub_keyboard(self, url: str) -> InlineKeyboardMarkup:
        return build_subscription_keyboard(url, self.get_short_callback_data, enable_latency_tester=config.ENABLE_LATENCY_TESTER)

    def get_short_callback_data(self, action: str, url: str) -> str:
        hash_key = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
        self.url_cache[hash_key] = {"url": url, "ts": time.time()}
        self.url_cache.move_to_end(hash_key)
        return f"{action}:{hash_key}"

    def cleanup_url_cache(self) -> None:
        now = time.time()
        expired_keys = [key for key, value in self.url_cache.items() if now - value.get("ts", 0) > self.url_cache_ttl_seconds]
        for key in expired_keys:
            self.url_cache.pop(key, None)
        while len(self.url_cache) > self.url_cache_max_size:
            self.url_cache.popitem(last=False)

    async def periodic_cache_cleanup(self, context: ContextTypes.DEFAULT_TYPE):
        def _cleanup_all():
            self.cleanup_url_cache()
            self.export_cache_service.cleanup_expired()

        await run_cache_cleanup(context, _cleanup_all)

    def is_authorized(self, update: Update) -> bool:
        user = update.effective_user
        return bool(user) and self.access_service.is_authorized_uid(user.id)

    def is_owner(self, update: Update) -> bool:
        user = update.effective_user
        return bool(user) and self.access_service.is_owner_uid(user.id)

    def record_interaction(self, update: Update, source: str) -> None:
        user = update.effective_user
        if not user:
            return
        self.user_profile_service.touch_user(
            user=user,
            source=source,
            is_owner=self.access_service.is_owner_uid(user.id),
            is_authorized=self.access_service.is_authorized_uid(user.id),
        )

    def with_profile_tracking(self, handler, source_getter):
        async def wrapped(update, context):
            self.record_interaction(update, source_getter(update, context))
            return await handler(update, context)

        return wrapped

    async def send_no_permission_msg(self, update: Update):
        msg = self.access_service.get_no_permission_message()
        try:
            if update.message:
                await update.message.reply_text(msg, parse_mode="HTML")
            elif update.callback_query:
                await update.callback_query.answer(self.access_service.get_no_permission_alert(), show_alert=True)
        except Exception as exc:
            self.logger.warning("发送权限拒绝提示失败: %s", exc)

    @staticmethod
    def schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, user_msg=None, bot_msg=None, delay=30):
        async def _delete_job(cb_context: ContextTypes.DEFAULT_TYPE):
            del cb_context
            try:
                if user_msg:
                    await user_msg.delete()
            except Exception:
                pass
            try:
                if bot_msg:
                    await bot_msg.delete()
            except Exception:
                pass

        if context.job_queue:
            context.job_queue.run_once(_delete_job, delay)

    @staticmethod
    def schedule_result_collapse(*, context, message, info, url, formatter, reply_markup, delay=20):
        async def _collapse_job(cb_context: ContextTypes.DEFAULT_TYPE):
            del cb_context
            try:
                await message.edit_text(
                    formatter(info, url),
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
            except Exception:
                return

        if context.job_queue:
            context.job_queue.run_once(_collapse_job, delay)


def create_runtime(*, logger: logging.Logger, proxy_port: int, url_cache_max_size: int, url_cache_ttl_seconds: int, allowed_user_ids: set[int]) -> Runtime:
    ws_manager = WorkspaceManager("data")
    access_state_store = AccessStateStore(os.path.join("data", "db", "access_state.json"))
    usage_audit_service = UsageAuditService(os.path.join("data", "logs", "usage_audit.jsonl"))
    user_profile_service = UserProfileService(os.path.join("data", "db", "user_profiles.json"))
    export_cache_service = ExportCacheService(
        index_path=os.path.join("data", "db", "export_cache_index.json"),
        cache_dir=os.path.join("data", "cache_exports"),
    )
    backup_service = BackupService(base_dir="data")
    user_manager = UserManager(os.path.join("data", "db", "users.json"), config.OWNER_ID)
    access_service = AccessService(user_manager, access_state_store, allowed_user_ids)
    runtime = Runtime(
        logger=logger,
        proxy_port=proxy_port,
        url_cache_max_size=url_cache_max_size,
        url_cache_ttl_seconds=url_cache_ttl_seconds,
        allowed_user_ids=allowed_user_ids,
        ws_manager=ws_manager,
        access_state_store=access_state_store,
        usage_audit_service=usage_audit_service,
        user_profile_service=user_profile_service,
        export_cache_service=export_cache_service,
        backup_service=backup_service,
        user_manager=user_manager,
        access_service=access_service,
        admin_service=None,
        conversion_service=None,
        document_service=None,
    )
    runtime.admin_service = AdminService(
        get_storage=runtime.get_storage,
        user_manager=runtime.user_manager,
        owner_id=config.OWNER_ID,
        format_traffic=format_traffic,
        access_service=runtime.access_service,
        usage_audit_service=runtime.usage_audit_service,
        user_profile_service=runtime.user_profile_service,
        export_cache_service=runtime.export_cache_service,
    )
    runtime.conversion_service = ConversionService(
        workspace_manager=runtime.ws_manager,
        latency_runner=_async_run_node_latency_test,
        export_cache_service=runtime.export_cache_service,
    )
    runtime.document_service = DocumentService(
        get_parser=runtime.get_parser,
        get_storage=runtime.get_storage,
        logger=runtime.logger,
        export_cache_service=runtime.export_cache_service,
    )
    return runtime


def build_handlers(runtime: Runtime, *, post_init):
    handlers = {}
    handlers["start"] = make_start_command(is_authorized=runtime.is_authorized, is_owner=runtime.is_owner, send_no_permission_msg=runtime.send_no_permission_msg, logger=runtime.logger)
    handlers["help"] = make_help_command(is_authorized=runtime.is_authorized, is_owner=runtime.is_owner, send_no_permission_msg=runtime.send_no_permission_msg, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["stats"] = make_stats_command(is_authorized=runtime.is_authorized, is_owner=runtime.is_owner, send_no_permission_msg=runtime.send_no_permission_msg, get_storage=runtime.get_storage, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["check"] = make_check_command(
        is_authorized=runtime.is_authorized,
        send_no_permission_msg=runtime.send_no_permission_msg,
        get_storage=runtime.get_storage,
        get_parser=runtime.get_parser,
        format_traffic=format_traffic,
        make_sub_keyboard=runtime.make_sub_keyboard,
        usage_audit_service=runtime.usage_audit_service,
        logger=runtime.logger,
    )
    handlers["list"] = make_list_command(
        is_authorized=runtime.is_authorized,
        send_no_permission_msg=runtime.send_no_permission_msg,
        get_storage=runtime.get_storage,
        get_short_callback_data=runtime.get_short_callback_data,
        button_labels={"recheck": BTN_RECHECK, "tag": BTN_TAG, "delete": BTN_DELETE},
        telegram_inline_button=InlineKeyboardButton,
        telegram_inline_markup=InlineKeyboardMarkup,
        schedule_auto_delete=runtime.schedule_auto_delete,
    )
    handlers["checkall"] = make_checkall_command(
        is_owner=runtime.is_owner,
        owner_only_msg=OWNER_ONLY_MSG,
        get_storage=runtime.get_storage,
        get_parser=runtime.get_parser,
        make_sub_keyboard=runtime.make_sub_keyboard,
        admin_service=runtime.admin_service,
        usage_audit_service=runtime.usage_audit_service,
        schedule_auto_delete=runtime.schedule_auto_delete,
    )
    handlers["broadcast"] = make_broadcast_command(
        is_owner=runtime.is_owner,
        owner_only_msg=OWNER_ONLY_MSG,
        user_manager=runtime.user_manager,
        schedule_auto_delete=runtime.schedule_auto_delete,
        logger=runtime.logger,
    )
    handlers["allowall"] = make_set_public_access_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, access_service=runtime.access_service, enabled=True, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["denyall"] = make_set_public_access_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, access_service=runtime.access_service, enabled=False, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["usageaudit"] = make_usage_audit_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, admin_service=runtime.admin_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["delete"] = make_delete_command(
        is_authorized=runtime.is_authorized,
        send_no_permission_msg=runtime.send_no_permission_msg,
        get_storage=runtime.get_storage,
        is_owner=runtime.is_owner,
        confirm_delete_label=BTN_CONFIRM_DELETE,
        get_short_callback_data=runtime.get_short_callback_data,
        inline_keyboard_button=InlineKeyboardButton,
        inline_keyboard_markup=InlineKeyboardMarkup,
        schedule_auto_delete=runtime.schedule_auto_delete,
    )
    handlers["export"] = make_export_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, get_storage=runtime.get_storage, schedule_auto_delete=runtime.schedule_auto_delete, admin_service=runtime.admin_service)
    handlers["import"] = make_import_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["backup"] = make_backup_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, backup_service=runtime.backup_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["restore"] = make_restore_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["adduser"] = make_add_user_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, user_manager=runtime.user_manager, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["deluser"] = make_del_user_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, user_manager=runtime.user_manager, owner_id=config.OWNER_ID, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["listusers"] = make_list_users_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, admin_service=runtime.admin_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["refresh_menu"] = make_refresh_menu_command(is_owner=runtime.is_owner, post_init=post_init)
    handlers["globallist"] = make_globallist_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, admin_service=runtime.admin_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["to_yaml"] = make_to_yaml_command(is_authorized=runtime.is_authorized, send_no_permission_msg=runtime.send_no_permission_msg, conversion_service=runtime.conversion_service)
    handlers["to_txt"] = make_to_txt_command(is_authorized=runtime.is_authorized, send_no_permission_msg=runtime.send_no_permission_msg, conversion_service=runtime.conversion_service)
    handlers["deepcheck"] = make_deepcheck_command(is_authorized=runtime.is_authorized, send_no_permission_msg=runtime.send_no_permission_msg, conversion_service=runtime.conversion_service, logger=runtime.logger)
    handlers["handle_document"] = make_document_handler(
        is_authorized=runtime.is_authorized,
        send_no_permission_msg=runtime.send_no_permission_msg,
        input_detector=InputDetector,
        is_owner=runtime.is_owner,
        owner_only_msg=OWNER_ONLY_MSG,
        document_service=runtime.document_service,
        format_subscription_info=format_subscription_info,
        format_subscription_compact=format_subscription_compact,
        make_sub_keyboard=runtime.make_sub_keyboard,
        schedule_result_collapse=runtime.schedule_result_collapse,
        backup_service=runtime.backup_service,
        usage_audit_service=runtime.usage_audit_service,
        logger=runtime.logger,
    )
    handle_node_text = make_node_text_handler(document_service=runtime.document_service, format_subscription_info=format_subscription_info, logger=runtime.logger)
    handle_subscription = make_subscription_handler(
        is_valid_url=is_valid_url,
        document_service=runtime.document_service,
        format_subscription_info=format_subscription_info,
        format_subscription_compact=format_subscription_compact,
        make_sub_keyboard=runtime.make_sub_keyboard,
        schedule_result_collapse=runtime.schedule_result_collapse,
        usage_audit_service=runtime.usage_audit_service,
        logger=runtime.logger,
    )
    handlers["handle_message"] = make_message_handler(
        is_authorized=runtime.is_authorized,
        send_no_permission_msg=runtime.send_no_permission_msg,
        is_owner=runtime.is_owner,
        get_storage=runtime.get_storage,
        input_detector=InputDetector,
        handle_document=handlers["handle_document"],
        handle_subscription=handle_subscription,
        handle_node_text=handle_node_text,
        tag_forbidden_msg=TAG_FORBIDDEN_MSG,
    )
    subscription_callback_handler = make_subscription_callback_handler(
        get_storage=runtime.get_storage,
        is_owner=runtime.is_owner,
        get_parser=runtime.get_parser,
        format_subscription_info=format_subscription_info,
        make_sub_keyboard=runtime.make_sub_keyboard,
        cleanup_url_cache=runtime.cleanup_url_cache,
        url_cache=runtime.url_cache,
        tag_forbidden_msg=TAG_FORBIDDEN_MSG,
        tag_exists_alert=TAG_EXISTS_ALERT,
        confirm_delete_label=BTN_CONFIRM_DELETE,
        inline_keyboard_button=InlineKeyboardButton,
        inline_keyboard_markup=InlineKeyboardMarkup,
        get_short_callback_data=runtime.get_short_callback_data,
        latency_tester=latency_tester,
        usage_audit_service=runtime.usage_audit_service,
        admin_service=runtime.admin_service,
        export_cache_service=runtime.export_cache_service,
        build_usage_audit_keyboard=build_usage_audit_keyboard,
        format_subscription_compact=format_subscription_compact,
        schedule_result_collapse=runtime.schedule_result_collapse,
        logger=runtime.logger,
    )
    handlers["button_callback"] = make_button_callback(is_authorized=runtime.is_authorized, no_permission_alert=runtime.access_service.get_no_permission_alert(), subscription_callback_handler=subscription_callback_handler)

    sources = {
        "start": lambda u, c: "/start",
        "help": lambda u, c: "/help",
        "stats": lambda u, c: "/stats",
        "check": lambda u, c: "/check",
        "list": lambda u, c: "/list",
        "checkall": lambda u, c: "/checkall",
        "broadcast": lambda u, c: "/broadcast",
        "allowall": lambda u, c: "/allowall",
        "denyall": lambda u, c: "/denyall",
        "usageaudit": lambda u, c: "/usageaudit",
        "delete": lambda u, c: "/delete",
        "export": lambda u, c: "/export",
        "import": lambda u, c: "/import",
        "backup": lambda u, c: "/backup",
        "restore": lambda u, c: "/restore",
        "adduser": lambda u, c: "/adduser",
        "deluser": lambda u, c: "/deluser",
        "listusers": lambda u, c: "/listusers",
        "refresh_menu": lambda u, c: "/refresh_menu",
        "globallist": lambda u, c: "/globallist",
        "to_yaml": lambda u, c: "/to_yaml",
        "to_txt": lambda u, c: "/to_txt",
        "deepcheck": lambda u, c: "/deepcheck",
        "handle_document": lambda u, c: f"document:{getattr(u.message.document, 'file_name', 'unknown')}",
        "handle_message": lambda u, c: "text_message",
        "button_callback": lambda u, c: f"callback:{getattr(u.callback_query, 'data', 'unknown')}",
    }
    return {name: runtime.with_profile_tracking(handler, sources[name]) for name, handler in handlers.items()}
