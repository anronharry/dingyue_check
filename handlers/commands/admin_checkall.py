"""Owner check-all command flow."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from core.models import SubscriptionEntity
from renderers.messages.admin_reports import render_checkall_report

AUTO_REMOVE_ERROR_CODES = {"auth_error", "not_found", "invalid_content", "ssl_error"}
AUTO_REMOVE_ERROR_SNIPPETS = (
    "已失效",
    "不存在",
    "无法识别订阅内容",
    "流量已耗尽",
    "流量已完全耗尽",
    "剩余 0 B",
    "SSL 证书校验失败",
)
CHECKALL_CONCURRENCY = 20
PROGRESS_UPDATE_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class CheckAllDeps:
    is_owner: Any
    owner_only_msg: str
    get_storage: Any
    get_parser: Any
    admin_service: Any
    usage_audit_service: Any
    schedule_auto_delete: Any
    subscription_check_service: Any = None


@dataclass
class CheckAllProgress:
    progress_msg: Any
    total_count: int
    completed_count: int = 0
    last_update_time: float = 0.0
    auto_removed_count: int = 0


def should_auto_remove_failed_subscription(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "").strip().lower()
    if code in AUTO_REMOVE_ERROR_CODES:
        return True
    error_text = str(exc or "")
    return any(token in error_text for token in AUTO_REMOVE_ERROR_SNIPPETS)


def make_checkall_command(
    *,
    is_owner,
    owner_only_msg,
    get_storage,
    get_parser,
    make_sub_keyboard,
    admin_service,
    usage_audit_service,
    schedule_auto_delete,
    subscription_check_service=None,
):
    del make_sub_keyboard
    deps = CheckAllDeps(
        is_owner=is_owner,
        owner_only_msg=owner_only_msg,
        get_storage=get_storage,
        get_parser=get_parser,
        admin_service=admin_service,
        usage_audit_service=usage_audit_service,
        schedule_auto_delete=schedule_auto_delete,
        subscription_check_service=subscription_check_service,
    )

    async def checkall_command(update, context):
        if not deps.is_owner(update):
            reply_msg = await update.message.reply_text(deps.owner_only_msg)
            deps.schedule_auto_delete(context, update.message, reply_msg, delay=10)
            return
        store = deps.get_storage()
        subscriptions = store.get_all()
        if not subscriptions:
            reply_msg = await update.message.reply_text("没有可检查的订阅记录。")
            deps.schedule_auto_delete(context, update.message, reply_msg, delay=30)
            return
        await _run_checkall(update, context, store, subscriptions, deps)

    return checkall_command


async def _run_checkall(
    update: Any,
    context: Any,
    store: Any,
    subscriptions: dict[str, Any],
    deps: CheckAllDeps,
) -> None:
    deps.usage_audit_service.log_check(
        user=update.effective_user,
        urls=list(subscriptions.keys()),
        source="/checkall",
    )
    progress = await _start_progress(update, context, len(subscriptions), deps)
    results = await _check_all_subscriptions(store, subscriptions, progress, deps)
    await _send_checkall_report(update, context, results, progress, deps)


async def _start_progress(
    update: Any, context: Any, total_count: int, deps: CheckAllDeps
) -> CheckAllProgress:
    progress_msg = await update.message.reply_text(
        "<b>正在检查全部用户订阅...</b>\n请稍候...",
        parse_mode="HTML",
    )
    deps.schedule_auto_delete(context, update.message, progress_msg, delay=60)
    return CheckAllProgress(
        progress_msg=progress_msg,
        total_count=total_count,
        last_update_time=time.time(),
    )


async def _check_all_subscriptions(
    store: Any,
    subscriptions: dict[str, Any],
    progress: CheckAllProgress,
    deps: CheckAllDeps,
) -> list[SubscriptionEntity]:
    semaphore = asyncio.Semaphore(CHECKALL_CONCURRENCY)
    store.begin_batch()
    results = await asyncio.gather(
        *[
            _check_one_global(url, data, store, semaphore, progress, deps)
            for url, data in subscriptions.items()
        ]
    )
    store.end_batch(save=True)
    return results


async def _check_one_global(
    url: str,
    data: dict[str, Any],
    store: Any,
    semaphore: asyncio.Semaphore,
    progress: CheckAllProgress,
    deps: CheckAllDeps,
) -> SubscriptionEntity:
    async with semaphore:
        try:
            result = await _parse_global_subscription(url, data, store, deps)
            entity = SubscriptionEntity.from_parse_result(
                url=url, result=result, owner_uid=data.get("owner_uid", 0)
            )
        except Exception as exc:
            entity = _handle_checkall_failure(url, data, store, exc, progress)
        await _update_progress(progress)
        return entity


async def _parse_global_subscription(
    url: str, data: dict[str, Any], store: Any, deps: CheckAllDeps
) -> dict[str, Any]:
    original_owner = data.get("owner_uid", 0)
    if deps.subscription_check_service:
        result = await deps.subscription_check_service.parse_and_store(
            url=url, owner_uid=original_owner
        )
    else:
        parser_instance = await deps.get_parser()
        result = await parser_instance.parse(url)
        store.add_or_update(url, result, user_id=original_owner)
    if result.get("remaining") is not None and result["remaining"] <= 0:
        raise Exception("流量已耗尽")
    return result


def _handle_checkall_failure(
    url: str,
    data: dict[str, Any],
    store: Any,
    exc: Exception,
    progress: CheckAllProgress,
) -> SubscriptionEntity:
    store.mark_check_failed(url, str(exc))
    if should_auto_remove_failed_subscription(exc):
        removed = store.remove(url)
        if removed:
            progress.auto_removed_count += 1
    return SubscriptionEntity.from_failure(
        url=url,
        name=data.get("name", "未知"),
        error=str(exc),
        owner_uid=data.get("owner_uid", 0),
    )


async def _update_progress(progress: CheckAllProgress) -> None:
    progress.completed_count += 1
    current_time = time.time()
    should_update = current_time - progress.last_update_time > PROGRESS_UPDATE_INTERVAL_SECONDS
    if not should_update and progress.completed_count != progress.total_count:
        return
    try:
        await progress.progress_msg.edit_text(
            f"正在检查全部用户订阅：{progress.completed_count} / {progress.total_count} ..."
        )
        progress.last_update_time = current_time
    except Exception:
        pass


async def _send_checkall_report(
    update: Any,
    context: Any,
    results: list[SubscriptionEntity],
    progress: CheckAllProgress,
    deps: CheckAllDeps,
) -> None:
    batch = deps.admin_service.to_batch_result(results)
    report = render_checkall_report(
        batch=batch,
        viewer_uid=update.effective_user.id,
        format_user_identity=deps.admin_service.user_profile_service.format_user_identity,
    )
    if progress.auto_removed_count > 0:
        report += f"\n\n已自动清理失效订阅: {progress.auto_removed_count} 条。"
    try:
        await progress.progress_msg.edit_text(report, parse_mode="HTML")
    except Exception:
        report_msg = await update.message.reply_text(report, parse_mode="HTML")
        deps.schedule_auto_delete(context, update.message, report_msg, delay=60)
