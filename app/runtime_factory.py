"""Runtime construction helpers."""
from __future__ import annotations

import logging
import os

from app import config
from app.runtime import Runtime
from core.access_control import UserManager
from core.access_state import AccessStateStore
from core.node_tester import _async_run_node_latency_test
from core.workspace_manager import WorkspaceManager
from features import latency_tester
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
from utils.utils import format_traffic


def create_runtime(*, logger: logging.Logger, proxy_port: int, url_cache_max_size: int, url_cache_ttl_seconds: int, allowed_user_ids: set[int]) -> Runtime:
    ws_manager = WorkspaceManager("data")
    access_state_store = AccessStateStore(os.path.join("data", "db", "access_state.json"))
    usage_audit_service = UsageAuditService(os.path.join("data", "logs", "usage_audit.jsonl"))
    user_profile_service = UserProfileService(os.path.join("data", "db", "user_profiles.json"))
    alert_preference_service = AlertPreferenceService(os.path.join("data", "db", "alert_preferences.json"))
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
        alert_preference_service=alert_preference_service,
        export_cache_service=export_cache_service,
        backup_service=backup_service,
        user_manager=user_manager,
        access_service=access_service,
        admin_service=None,
        conversion_service=None,
        document_service=None,
        subscription_check_service=None,
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
    runtime.subscription_check_service = SubscriptionCheckService(
        get_parser=runtime.get_parser,
        get_storage=runtime.get_storage,
        logger=runtime.logger,
        export_cache_service=runtime.export_cache_service,
        global_concurrency=config.PARSE_GLOBAL_CONCURRENCY,
        user_concurrency=config.PARSE_USER_CONCURRENCY,
        retry_attempts=2,
        retry_backoff_seconds=0.35,
        slow_threshold_seconds=config.PARSE_SLOW_THRESHOLD_SECONDS,
        stats_report_every=config.PARSE_STATS_REPORT_EVERY,
    )
    runtime.document_service = DocumentService(
        get_parser=runtime.get_parser,
        get_storage=runtime.get_storage,
        logger=runtime.logger,
        export_cache_service=runtime.export_cache_service,
        quick_ping_runner=latency_tester.ping_all_nodes,
        subscription_check_service=runtime.subscription_check_service,
    )
    return runtime
