"""Runtime container and shared runtime helpers."""
from __future__ import annotations

import time
import secrets
import logging
from collections import OrderedDict
from dataclasses import dataclass

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from core.parser import SubscriptionParser
from core.storage_enhanced import SubscriptionStorage
from core.workspace_manager import WorkspaceManager
from jobs.cache_cleanup_job import run_cache_cleanup
from renderers.telegram_keyboards import build_subscription_keyboard
from services.access_service import AccessService
from services.admin_service import AdminService
from services.alert_preference_service import AlertPreferenceService
from services.backup_service import BackupService
from services.conversion_service import ConversionService
from services.document_service import DocumentService
from services.export_cache_service import ExportCacheService
from services.subscription_check_service import SubscriptionCheckService
from services.usage_audit_service import UsageAuditService
from services.user_profile_service import UserProfileService
from typing import Any


@dataclass
class Runtime:
    logger: logging.Logger
    proxy_port: int
    url_cache_max_size: int
    url_cache_ttl_seconds: int
    allowed_user_ids: set[int]
    ws_manager: WorkspaceManager
    access_state_store: Any
    usage_audit_service: UsageAuditService
    user_profile_service: UserProfileService
    alert_preference_service: AlertPreferenceService
    export_cache_service: ExportCacheService
    backup_service: BackupService
    user_manager: Any
    access_service: AccessService
    admin_service: AdminService
    conversion_service: ConversionService
    document_service: DocumentService
    subscription_check_service: SubscriptionCheckService
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
            self.parser = SubscriptionParser(
                proxy_port=self.proxy_port,
                use_proxy=False,
                session=self.shared_session,
                verify_ssl=config.VERIFY_SSL,
                max_parse_concurrency=config.PARSE_GLOBAL_CONCURRENCY,
                success_cache_ttl_seconds=config.PARSE_SUCCESS_CACHE_TTL_SECONDS,
                success_cache_max_size=config.PARSE_SUCCESS_CACHE_MAX_SIZE,
            )
        return self.parser

    def make_sub_keyboard(
        self,
        url: str,
        *,
        owner_mode: bool = False,
        user_actions_expanded: bool = False,
    ) -> InlineKeyboardMarkup:
        return build_subscription_keyboard(
            url,
            self.get_short_callback_data,
            enable_latency_tester=config.ENABLE_LATENCY_TESTER,
            owner_mode=owner_mode,
            compact_user_mode=config.ENABLE_USER_COMPACT_SUB_BUTTONS,
            user_actions_expanded=user_actions_expanded,
        )

    def get_short_callback_data(self, action: str, url: str) -> str:
        token = secrets.token_hex(8)
        while token in self.url_cache:
            token = secrets.token_hex(8)
        self.url_cache[token] = {"url": url, "ts": time.time()}
        self.url_cache.move_to_end(token)
        return f"{action}:{token}"

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
            self.user_profile_service.flush()
            self.alert_preference_service.flush()
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
            except Exception as exc:
                logging.getLogger(__name__).error("Auto-collapse edit_text failed: %s", exc, exc_info=True)

        if context.job_queue:
            context.job_queue.run_once(_collapse_job, delay)
        else:
            logging.getLogger(__name__).warning("Job queue not available, skipping auto-collapse.")


def create_runtime(*, logger: logging.Logger, proxy_port: int, url_cache_max_size: int, url_cache_ttl_seconds: int, allowed_user_ids: set[int]) -> Runtime:
    from app.runtime_factory import create_runtime as _create_runtime

    return _create_runtime(
        logger=logger,
        proxy_port=proxy_port,
        url_cache_max_size=url_cache_max_size,
        url_cache_ttl_seconds=url_cache_ttl_seconds,
        allowed_user_ids=allowed_user_ids,
    )


def build_handlers(runtime: Runtime, *, post_init):
    from app.handlers_builder import build_handlers as _build_handlers

    return _build_handlers(runtime, post_init=post_init)
