"""Document and node-text message handlers."""

from __future__ import annotations

from handlers.messages.document_flows import (
    MAX_DOCUMENT_SIZE_BYTES,
    DocumentFlowDeps,
    build_reply_kwargs,
    download_document_bytes,
    get_file_name,
    handle_json_import,
    handle_node_document,
    handle_restore_upload,
    handle_txt_subscription_file,
    short_error,
)


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
    deps = DocumentFlowDeps(
        is_owner=is_owner,
        owner_only_msg=owner_only_msg,
        document_service=document_service,
        format_subscription_info=format_subscription_info,
        make_sub_keyboard=make_sub_keyboard,
        backup_service=backup_service,
        usage_audit_service=usage_audit_service,
        logger=logger,
    )

    async def handle_document(update, context):
        if await handle_restore_upload(update, context, deps):
            return
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return

        document = update.message.document
        file_name = get_file_name(document)
        reply_kwargs = build_reply_kwargs(update)
        file_type = input_detector.detect_file_type(file_name)
        if file_type == "unknown":
            await update.message.reply_text(
                "暂不支持该文件类型。请上传 TXT/YAML；导入 JSON 请先执行 /import。", **reply_kwargs
            )
            return

        processing_msg = await update.message.reply_text(_progress_text(file_type), **reply_kwargs)
        if document.file_size and document.file_size > MAX_DOCUMENT_SIZE_BYTES:
            await processing_msg.edit_text("文件过大：超过 5MB 限制。")
            return

        await _process_document_content(file_type, file_name, update, context, processing_msg, deps)

    return handle_document


def _progress_text(file_type: str) -> str:
    if file_type in {"txt", "yaml"}:
        return f"🚀 已接收 {file_type.upper()} 文件，正在解析并执行快速检测..."
    return f"🚀 已接收 {file_type.upper()} 文件，正在解析内容..."


async def _process_document_content(file_type, file_name, update, context, processing_msg, deps):
    try:
        content_bytes = await download_document_bytes(update.message.document)
        if file_type == "json":
            await handle_json_import(content_bytes, update, context, processing_msg, deps)
            return
        if file_type == "txt" and await handle_txt_subscription_file(
            content_bytes,
            file_name,
            update,
            processing_msg,
            deps,
        ):
            return
        await handle_node_document(
            content_bytes, file_name, file_type, update, processing_msg, deps
        )
    except Exception as exc:
        deps.logger.error("文件处理失败: %s", exc)
        await _reply_document_error(exc, update, processing_msg, deps.logger)


async def _reply_document_error(exc, update, processing_msg, logger):
    reply_kwargs = build_reply_kwargs(update)
    try:
        await processing_msg.edit_text(f"文件处理失败：{short_error(exc)}")
    except Exception:
        await update.message.reply_text(f"文件处理失败：{short_error(exc)}", **reply_kwargs)


def make_node_text_handler(*, document_service, format_subscription_info, logger):

    async def handle_node_text(update, context):
        del context
        reply_kwargs = build_reply_kwargs(update)
        processing_msg = await update.message.reply_text(
            "正在解析节点文本并执行快速检测...", **reply_kwargs
        )
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
            try:
                await processing_msg.edit_text(f"节点解析失败：{short_error(exc)}")
            except Exception:
                await update.message.reply_text(f"节点解析失败：{short_error(exc)}", **reply_kwargs)

    return handle_node_text
