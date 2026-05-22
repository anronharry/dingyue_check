"""Subscription check command flow."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from core.models import BatchCheckResult, SubscriptionEntity
from renderers.messages.admin_reports import render_subscription_check_report

AUTO_REMOVE_ERROR_CODES = {"auth_error", "not_found", "invalid_content", "ssl_error"}
AUTO_REMOVE_ERROR_SNIPPETS = (
    "已失效",
    "不存在",
    "无法识别订阅内容",
    "流量已完全耗尽",
    "剩余 0 B",
    "SSL 证书校验失败",
)
CHECK_CONCURRENCY = 20
PROGRESS_UPDATE_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class CheckCommandDeps:
    is_authorized: Any
    send_no_permission_msg: Any
    get_storage: Any
    get_parser: Any
    format_traffic: Any
    usage_audit_service: Any
    logger: Any
    subscription_check_service: Any = None


@dataclass
class CheckProgress:
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


def make_check_command(
    *,
    is_authorized,
    is_owner,
    send_no_permission_msg,
    get_storage,
    get_parser,
    format_traffic,
    make_sub_keyboard,
    usage_audit_service,
    logger,
    subscription_check_service=None,
):
    del is_owner, make_sub_keyboard
    deps = CheckCommandDeps(
        is_authorized=is_authorized,
        send_no_permission_msg=send_no_permission_msg,
        get_storage=get_storage,
        get_parser=get_parser,
        format_traffic=format_traffic,
        usage_audit_service=usage_audit_service,
        logger=logger,
        subscription_check_service=subscription_check_service,
    )

    async def check_command(update, context):
        if not deps.is_authorized(update):
            await deps.send_no_permission_msg(update)
            return

        store = deps.get_storage()
        uid = update.effective_user.id
        subscriptions, message = _select_subscriptions(store, uid, context.args)
        if not subscriptions:
            await update.message.reply_text(message)
            return

        deps.usage_audit_service.log_check(
            user=update.effective_user,
            urls=list(subscriptions.keys()),
            source="/check",
        )
        progress_msg = await update.message.reply_text(message)
        progress = CheckProgress(
            progress_msg=progress_msg, total_count=len(subscriptions), last_update_time=time.time()
        )
        await _run_batch_check(store, uid, subscriptions, progress, deps, update)

    return check_command


def _select_subscriptions(store: Any, uid: int, args: list[str]) -> tuple[dict[str, Any], str]:
    tag = args[0] if args else None
    user_subs = store.get_by_user(uid)
    if tag:
        subscriptions = {
            url: data for url, data in user_subs.items() if tag in data.get("tags", [])
        }
        message = f"🔍 正在检测标签 '{tag}' 下的订阅（共 {len(subscriptions)} 个）..."
        return subscriptions, message if subscriptions else f"📭 标签 '{tag}' 下没有订阅"
    message = f"🔍 正在检测您的订阅（共 {len(user_subs)} 个）..."
    return user_subs, message if user_subs else "📭 暂无订阅记录，请先发送订阅链接。"


async def _run_batch_check(
    store: Any,
    uid: int,
    subscriptions: dict[str, Any],
    progress: CheckProgress,
    deps: CheckCommandDeps,
    update: Any,
) -> None:
    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)
    store.begin_batch()
    results = await asyncio.gather(
        *[
            _check_one(url, data, store, uid, semaphore, progress, deps)
            for url, data in subscriptions.items()
        ]
    )
    store.end_batch(save=True)
    await _send_final_report(results, progress, update, deps)


async def _check_one(
    url: str,
    data: dict[str, Any],
    store: Any,
    uid: int,
    semaphore: asyncio.Semaphore,
    progress: CheckProgress,
    deps: CheckCommandDeps,
) -> SubscriptionEntity:
    async with semaphore:
        try:
            result = await _parse_subscription(url, data, store, uid, deps)
            entity = SubscriptionEntity.from_parse_result(
                url=url, result=result, owner_uid=data.get("owner_uid", uid)
            )
        except Exception as exc:
            entity = _handle_check_failure(url, data, store, uid, exc, progress, deps)
        await _update_progress(progress)
        return entity


async def _parse_subscription(
    url: str, data: dict[str, Any], store: Any, uid: int, deps: CheckCommandDeps
) -> dict[str, Any]:
    owner_uid = data.get("owner_uid", uid)
    if deps.subscription_check_service:
        result = await deps.subscription_check_service.parse_and_store(url=url, owner_uid=owner_uid)
    else:
        parser_instance = await deps.get_parser()
        result = await parser_instance.parse(url)
        store.add_or_update(url, result)
    if result.get("remaining") is not None and result["remaining"] <= 0:
        raise Exception("当前订阅流量已完全耗尽（剩余 0 B）")
    return result


def _handle_check_failure(
    url: str,
    data: dict[str, Any],
    store: Any,
    uid: int,
    exc: Exception,
    progress: CheckProgress,
    deps: CheckCommandDeps,
) -> SubscriptionEntity:
    deps.logger.error("检测失败 %s: %s", url, exc)
    store.mark_check_failed(url, str(exc), operator_uid=uid, require_owner=True)
    if should_auto_remove_failed_subscription(exc):
        removed = store.remove(url, operator_uid=uid, require_owner=True)
        if removed:
            progress.auto_removed_count += 1
    return SubscriptionEntity.from_failure(
        url=url,
        name=data.get("name", "未知"),
        error=str(exc),
        owner_uid=data.get("owner_uid", uid),
    )


async def _update_progress(progress: CheckProgress) -> None:
    progress.completed_count += 1
    current_time = time.time()
    should_update = current_time - progress.last_update_time > PROGRESS_UPDATE_INTERVAL_SECONDS
    if not should_update and progress.completed_count != progress.total_count:
        return
    try:
        await progress.progress_msg.edit_text(
            f"⏳ 正在检测: {progress.completed_count} / {progress.total_count} 完成..."
        )
        progress.last_update_time = current_time
    except Exception:
        pass


async def _send_final_report(
    results: list[SubscriptionEntity],
    progress: CheckProgress,
    update: Any,
    deps: CheckCommandDeps,
) -> None:
    batch = BatchCheckResult(entries=results)
    final_report = render_subscription_check_report(batch=batch, format_traffic=deps.format_traffic)
    if progress.auto_removed_count > 0:
        final_report += f"\n\n已自动清理失效订阅: {progress.auto_removed_count} 条。"
    try:
        await progress.progress_msg.edit_text(final_report, parse_mode="HTML")
    except Exception:
        await update.message.reply_text(final_report, parse_mode="HTML")
