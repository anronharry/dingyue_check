"""Document upload flow helpers."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any


MAX_DOCUMENT_SIZE_BYTES = 5 * 1024 * 1024
MAX_RESTORE_ZIP_SIZE_BYTES = 20 * 1024 * 1024
MAX_ERROR_TEXT_LENGTH = 500


@dataclass(frozen=True)
class DocumentFlowDeps:
    is_owner: Any
    owner_only_msg: str
    document_service: Any
    format_subscription_info: Any
    make_sub_keyboard: Any
    backup_service: Any
    usage_audit_service: Any
    logger: Any


def build_reply_kwargs(update: Any) -> dict[str, int]:
    message_id = getattr(update.message, "message_id", None)
    return {"reply_to_message_id": message_id} if message_id else {}


def get_file_name(document: Any) -> str:
    return (getattr(document, "file_name", "") or "").strip()


def short_error(exc: Exception) -> str:
    error_msg = str(exc)
    suffix = "..." if len(error_msg) > MAX_ERROR_TEXT_LENGTH else ""
    return f"{error_msg[:MAX_ERROR_TEXT_LENGTH]}{suffix}"


def make_sub_keyboard_safe(
    make_sub_keyboard: Any,
    *,
    url: str,
    owner_mode: bool,
    operator_uid: int,
) -> Any:
    try:
        return make_sub_keyboard(url, operator_uid=operator_uid, owner_mode=owner_mode)
    except TypeError:
        return make_sub_keyboard(url, owner_mode=owner_mode)


async def download_document_bytes(document: Any) -> bytes:
    telegram_file = await document.get_file()
    return bytes(await telegram_file.download_as_bytearray())


async def handle_restore_upload(update: Any, context: Any, deps: DocumentFlowDeps) -> bool:
    document = update.message.document
    file_name = get_file_name(document)
    if not context.user_data.get("awaiting_restore") or not file_name.lower().endswith(".zip"):
        return False

    reply_kwargs = build_reply_kwargs(update)
    if document.file_size and document.file_size > MAX_RESTORE_ZIP_SIZE_BYTES:
        await update.message.reply_text("备份 ZIP 过大（最大 20MB），已拒绝恢复。", **reply_kwargs)
        return True

    processing_msg = await update.message.reply_text("正在恢复备份，请稍候...", **reply_kwargs)
    temp_zip_path = _build_restore_temp_path(update.effective_user.id)
    try:
        await _save_restore_zip(document, temp_zip_path)
        restored = await _restore_backup(deps.backup_service, temp_zip_path)
        context.user_data.pop("awaiting_restore", None)
        await processing_msg.edit_text(f"恢复完成，共写入 {len(restored)} 个文件。")
    except Exception as exc:
        deps.logger.error("备份恢复失败: %s", exc)
        await processing_msg.edit_text(f"备份恢复失败：{exc}")
    finally:
        _remove_restore_temp_file(temp_zip_path, deps.logger)
    return True


def _build_restore_temp_path(user_id: int) -> str:
    temp_dir = os.path.join("data", "temp")
    os.makedirs(temp_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(temp_dir, f"restore_upload_{timestamp}_{user_id}.zip")


async def _save_restore_zip(document: Any, temp_zip_path: str) -> None:
    telegram_file = await document.get_file()
    if hasattr(telegram_file, "download_to_drive"):
        await telegram_file.download_to_drive(custom_path=temp_zip_path)
        return
    with open(temp_zip_path, "wb") as handle:
        handle.write(bytes(await telegram_file.download_as_bytearray()))


async def _restore_backup(backup_service: Any, temp_zip_path: str) -> list[str]:
    if hasattr(backup_service, "restore_backup"):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, backup_service.restore_backup, temp_zip_path)
    with open(temp_zip_path, "rb") as handle:
        return backup_service.restore_backup_bytes(handle.read())


def _remove_restore_temp_file(temp_zip_path: str, logger: Any) -> None:
    try:
        if os.path.exists(temp_zip_path):
            os.remove(temp_zip_path)
    except OSError:
        logger.warning("清理恢复临时文件失败: %s", temp_zip_path)


async def handle_json_import(
    content_bytes: bytes, update: Any, context: Any, processing_msg: Any, deps: DocumentFlowDeps
) -> bool:
    if not deps.is_owner(update):
        await processing_msg.edit_text(deps.owner_only_msg)
        return True
    if not context.user_data.get("awaiting_import"):
        await processing_msg.edit_text("请先发送 /import，再上传导出的 JSON 文件。")
        return True
    imported_count = await deps.document_service.import_json(content_bytes=content_bytes)
    context.user_data.pop("awaiting_import", None)
    await processing_msg.edit_text(f"导入完成，共导入 {imported_count} 条订阅。")
    return True


async def handle_txt_subscription_file(
    content_bytes: bytes,
    file_name: str,
    update: Any,
    processing_msg: Any,
    deps: DocumentFlowDeps,
) -> bool:
    subscription_urls = deps.document_service.extract_subscription_urls(content_bytes=content_bytes)
    if not subscription_urls:
        return False

    _log_document_check(update, file_name, subscription_urls, deps.usage_audit_service)
    await processing_msg.edit_text(
        f"🚀 识别到 {len(subscription_urls)} 个订阅链接，正在检测并保存..."
    )
    results = await deps.document_service.parse_subscription_urls(
        subscription_urls=subscription_urls,
        owner_uid=update.effective_user.id,
    )
    await _delete_progress_message(processing_msg, deps.logger)
    await _send_subscription_results(results, update, deps)
    await _send_subscription_summary(subscription_urls, results, update)
    return True


def _log_document_check(
    update: Any, file_name: str, subscription_urls: list[str], usage_audit_service: Any
) -> None:
    if not usage_audit_service:
        return
    usage_audit_service.log_check(
        user=update.effective_user,
        urls=subscription_urls,
        source=f"document_import:{file_name or 'unknown'}",
    )


async def _send_subscription_results(
    results: list[dict[str, Any]], update: Any, deps: DocumentFlowDeps
) -> None:
    reply_kwargs = build_reply_kwargs(update)
    for item in sorted(results, key=lambda row: row["index"]):
        if item["status"] == "success":
            await _send_success_result(item, update, deps, reply_kwargs)
        else:
            await update.message.reply_text(
                f"❌ 订阅 {item['index']} 检测失败\n原因：{item['error']}",
                **reply_kwargs,
            )


async def _send_success_result(
    item: dict[str, Any], update: Any, deps: DocumentFlowDeps, reply_kwargs: dict[str, Any]
) -> None:
    message = f"<b>🔎 订阅 {item['index']} 检测结果</b>\n\n{deps.format_subscription_info(item['data'], item['url'])}"
    reply_markup = make_sub_keyboard_safe(
        deps.make_sub_keyboard,
        url=item["url"],
        operator_uid=update.effective_user.id,
        owner_mode=deps.is_owner(update),
    )
    await update.message.reply_text(
        message,
        parse_mode="HTML",
        reply_markup=reply_markup,
        **reply_kwargs,
    )


async def _send_subscription_summary(
    subscription_urls: list[str], results: list[dict[str, Any]], update: Any
) -> None:
    reply_kwargs = build_reply_kwargs(update)
    success_count = sum(1 for item in results if item["status"] == "success")
    failed_count = sum(1 for item in results if item["status"] == "failed")
    await update.message.reply_text(
        "<b>✅ 订阅文件处理完成</b>\n\n"
        f"识别数量：{len(subscription_urls)}\n"
        f"成功：{success_count}\n"
        f"失败：{failed_count}",
        parse_mode="HTML",
        **reply_kwargs,
    )


async def handle_node_document(
    content_bytes: bytes,
    file_name: str,
    file_type: str,
    update: Any,
    processing_msg: Any,
    deps: DocumentFlowDeps,
) -> None:
    result = await deps.document_service.analyze_document_nodes(
        file_name=file_name or "unknown",
        file_type=file_type,
        content_bytes=content_bytes,
        owner_uid=update.effective_user.id,
    )
    if not result:
        await processing_msg.edit_text("未从文件中解析到有效内容。")
        return

    message = (
        "<b>节点文件解析完成</b>\n\n"
        + deps.format_subscription_info(result)
        + "\n\n<i>这是节点列表，不包含订阅流量或到期信息。</i>"
    )
    await _delete_progress_message(processing_msg, deps.logger)
    await update.message.reply_text(message, parse_mode="HTML", **build_reply_kwargs(update))


async def _delete_progress_message(processing_msg: Any, logger: Any) -> None:
    try:
        await processing_msg.delete()
    except Exception as exc:
        logger.warning("删除进度消息失败: %s", exc)
