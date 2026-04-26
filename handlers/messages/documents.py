"""Document and node-text message handlers."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime


MAX_DOCUMENT_SIZE_BYTES = 5 * 1024 * 1024
MAX_RESTORE_ZIP_SIZE_BYTES = 20 * 1024 * 1024


def make_document_handler(
    *,
    is_authorized,
    send_no_permission_msg,
    input_detector,
    is_owner,
    owner_only_msg,
    document_service,
    format_subscription_info,
    make_sub_keyboard,
    backup_service,
    usage_audit_service,
    logger,
):
    def _make_sub_keyboard_safe(*, url: str, owner_mode: bool, operator_uid: int):
        try:
            return make_sub_keyboard(url, operator_uid=operator_uid, owner_mode=owner_mode)
        except TypeError:
            return make_sub_keyboard(url, owner_mode=owner_mode)

    async def handle_document(update, context):
        document = update.message.document
        file_name = (getattr(document, "file_name", "") or "").strip()
        reply_to_message_id = getattr(update.message, "message_id", None)
        reply_kwargs = {"reply_to_message_id": reply_to_message_id} if reply_to_message_id else {}

        if context.user_data.get("awaiting_restore") and file_name.lower().endswith(".zip"):
            if document.file_size and document.file_size > MAX_RESTORE_ZIP_SIZE_BYTES:
                await update.message.reply_text("备份 ZIP 过大（最大 20MB），已拒绝恢复。", **reply_kwargs)
                return

            processing_msg = await update.message.reply_text("正在恢复备份，请稍候...", **reply_kwargs)
            temp_dir = os.path.join("data", "temp")
            os.makedirs(temp_dir, exist_ok=True)
            temp_zip_path = os.path.join(
                temp_dir,
                f"restore_upload_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{update.effective_user.id}.zip",
            )
            try:
                telegram_file = await document.get_file()
                if hasattr(telegram_file, "download_to_drive"):
                    await telegram_file.download_to_drive(custom_path=temp_zip_path)
                else:
                    with open(temp_zip_path, "wb") as handle:
                        handle.write(bytes(await telegram_file.download_as_bytearray()))

                loop = asyncio.get_event_loop()
                if hasattr(backup_service, "restore_backup"):
                    restored = await loop.run_in_executor(None, backup_service.restore_backup, temp_zip_path)
                else:
                    with open(temp_zip_path, "rb") as handle:
                        restored = backup_service.restore_backup_bytes(handle.read())

                context.user_data.pop("awaiting_restore", None)
                await processing_msg.edit_text(f"恢复完成，共写入 {len(restored)} 个文件。")
            except Exception as exc:
                logger.error("备份恢复失败: %s", exc)
                await processing_msg.edit_text(f"备份恢复失败：{exc}")
            finally:
                try:
                    if os.path.exists(temp_zip_path):
                        os.remove(temp_zip_path)
                except OSError:
                    logger.warning("清理恢复临时文件失败: %s", temp_zip_path)
            return

        if not is_authorized(update):
            await send_no_permission_msg(update)
            return

        file_type = input_detector.detect_file_type(file_name)
        if file_type == "unknown":
            await update.message.reply_text("暂不支持该文件类型。请上传 TXT/YAML；导入 JSON 请先执行 /import。", **reply_kwargs)
            return

        if file_type in {"txt", "yaml"}:
            progress_text = f"🚀 已接收 {file_type.upper()} 文件，正在解析并执行快速检测..."
        else:
            progress_text = f"🚀 已接收 {file_type.upper()} 文件，正在解析内容..."
        processing_msg = await update.message.reply_text(progress_text, **reply_kwargs)

        if document.file_size and document.file_size > MAX_DOCUMENT_SIZE_BYTES:
            await processing_msg.edit_text("文件过大：超过 5MB 限制。")
            return

        try:
            telegram_file = await document.get_file()
            content_bytes = bytes(await telegram_file.download_as_bytearray())

            if file_type == "json":
                if not is_owner(update):
                    await processing_msg.edit_text(owner_only_msg)
                    return
                if not context.user_data.get("awaiting_import"):
                    await processing_msg.edit_text("请先发送 /import，再上传导出的 JSON 文件。")
                    return
                imported_count = await document_service.import_json(content_bytes=content_bytes)
                context.user_data.pop("awaiting_import", None)
                await processing_msg.edit_text(f"导入完成，共导入 {imported_count} 条订阅。")
                return

            if file_type == "txt":
                subscription_urls = document_service.extract_subscription_urls(content_bytes=content_bytes)
                if subscription_urls:
                    if usage_audit_service:
                        usage_audit_service.log_check(
                            user=update.effective_user,
                            urls=subscription_urls,
                            source=f"document_import:{file_name or 'unknown'}",
                        )
                    await processing_msg.edit_text(
                        f"🚀 识别到 {len(subscription_urls)} 个订阅链接，正在检测并保存..."
                    )
                    results = await document_service.parse_subscription_urls(
                        subscription_urls=subscription_urls,
                        owner_uid=update.effective_user.id,
                    )
                    try:
                        await processing_msg.delete()
                    except Exception as exc:
                        logger.warning("删除进度消息失败: %s", exc)

                    for item in sorted(results, key=lambda row: row["index"]):
                        if item["status"] == "success":
                            message = (
                                f"<b>🔎 订阅 {item['index']} 检测结果</b>\n\n"
                                f"{format_subscription_info(item['data'], item['url'])}"
                            )
                            reply_markup = _make_sub_keyboard_safe(
                                url=item["url"],
                                operator_uid=update.effective_user.id,
                                owner_mode=is_owner(update),
                            )
                            await update.message.reply_text(
                                message,
                                parse_mode="HTML",
                                reply_markup=reply_markup,
                                **reply_kwargs,
                            )
                        else:
                            await update.message.reply_text(
                                f"❌ 订阅 {item['index']} 检测失败\n原因：{item['error']}",
                                **reply_kwargs,
                            )

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
                    return

            result = await document_service.analyze_document_nodes(
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
                + format_subscription_info(result)
                + "\n\n<i>这是节点列表，不包含订阅流量或到期信息。</i>"
            )
            try:
                await processing_msg.delete()
            except Exception as exc:
                logger.warning("删除进度消息失败: %s", exc)
            await update.message.reply_text(message, parse_mode="HTML", **reply_kwargs)
        except Exception as exc:
            logger.error("文件处理失败: %s", exc)
            error_msg = str(exc)
            short_error = f"{error_msg[:500]}{'...' if len(error_msg) > 500 else ''}"
            try:
                await processing_msg.edit_text(f"文件处理失败：{short_error}")
            except Exception:
                await update.message.reply_text(f"文件处理失败：{short_error}", **reply_kwargs)

    return handle_document


def make_node_text_handler(*, document_service, format_subscription_info, logger):

    async def handle_node_text(update, context):
        del context
        reply_to_message_id = getattr(update.message, "message_id", None)
        reply_kwargs = {"reply_to_message_id": reply_to_message_id} if reply_to_message_id else {}
        processing_msg = await update.message.reply_text("正在解析节点文本并执行快速检测...", **reply_kwargs)
        try:
            result = await document_service.analyze_node_text(text=update.message.text.strip())
            if not result:
                await processing_msg.edit_text("未解析到有效节点。")
                return
            message = format_subscription_info(result)
            try:
                await processing_msg.delete()
            except Exception as exc:
                logger.warning("删除进度消息失败: %s", exc)
            await update.message.reply_text(message, parse_mode="HTML", **reply_kwargs)
        except Exception as exc:
            logger.error("节点文本解析失败: %s", exc)
            error_msg = str(exc)
            short_error = f"{error_msg[:500]}{'...' if len(error_msg) > 500 else ''}"
            try:
                await processing_msg.edit_text(f"节点解析失败：{short_error}")
            except Exception:
                await update.message.reply_text(f"节点解析失败：{short_error}", **reply_kwargs)

    return handle_node_text
