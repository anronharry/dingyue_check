"""Document and node-text message handlers."""
from __future__ import annotations


def make_document_handler(
    *,
    is_authorized,
    send_no_permission_msg,
    input_detector,
    is_owner,
    owner_only_msg,
    document_service,
    format_subscription_info,
    format_subscription_compact,
    make_sub_keyboard,
    schedule_result_collapse,
    backup_service,
    usage_audit_service,
    logger,
):
    async def handle_document(update, context):
        document = update.message.document
        if context.user_data.get("awaiting_restore") and document.file_name.lower().endswith(".zip"):
            processing_msg = await update.message.reply_text("📦 正在恢复全量备份...")
            telegram_file = await document.get_file()
            restored = backup_service.restore_backup_bytes(bytes(await telegram_file.download_as_bytearray()))
            context.user_data.pop("awaiting_restore", None)
            await processing_msg.edit_text(f"✅ 恢复完成，共写入 {len(restored)} 个文件")
            return

        if not is_authorized(update):
            await send_no_permission_msg(update)
            return

        file_type = input_detector.detect_file_type(document.file_name)
        if file_type == "unknown":
            await update.message.reply_text("❌ 不支持的文件类型，请上传 TXT / YAML；导入旧 JSON 先发 /import。")
            return
        processing_msg = await update.message.reply_text(f"📄 已收到 {file_type.upper()} 文件，正在识别内容...")
        if document.file_size > 5 * 1024 * 1024:
            await processing_msg.edit_text("❌ 文件过大：超过 5MB，已拒绝处理")
            return
        try:
            telegram_file = await document.get_file()
            content_bytes = bytes(await telegram_file.download_as_bytearray())
            if file_type == "json":
                if not is_owner(update):
                    await processing_msg.edit_text(owner_only_msg)
                    return
                if not context.user_data.get("awaiting_import"):
                    await processing_msg.edit_text("❌ 请先发送 /import，再上传导出的 JSON 文件")
                    return
                imported_count = await document_service.import_json(content_bytes=content_bytes)
                context.user_data.pop("awaiting_import", None)
                await processing_msg.edit_text(f"✅ 导入完成，共导入 {imported_count} 条订阅")
                return
            if file_type == "txt":
                subscription_urls = document_service.extract_subscription_urls(content_bytes=content_bytes)
                if subscription_urls:
                    usage_audit_service.log_check(
                        user=update.effective_user,
                        urls=subscription_urls,
                        source=f"文档导入:{document.file_name}",
                    )
                    await processing_msg.edit_text(f"🔗 检测到 {len(subscription_urls)} 个订阅链接，正在批量检测并保存...")
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
                            message = f"<b>📊 订阅 {item['index']} 检测结果</b>\n\n{format_subscription_info(item['data'], item['url'])}"
                            reply_markup = make_sub_keyboard(item["url"])
                            sent_msg = await update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)
                            schedule_result_collapse(
                                context=context,
                                message=sent_msg,
                                info=item["data"],
                                url=item["url"],
                                formatter=format_subscription_compact,
                                reply_markup=reply_markup,
                            )
                        else:
                            await update.message.reply_text(
                                f"❌ <b>订阅 {item['index']}</b> 检测失败\n原因：{item['error']}",
                                parse_mode="HTML",
                            )
                    success_count = sum(1 for item in results if item["status"] == "success")
                    failed_count = sum(1 for item in results if item["status"] == "failed")
                    await update.message.reply_text(
                        "<b>✅ 订阅文件处理完成</b>\n\n"
                        f"识别到的订阅数：{len(subscription_urls)}\n"
                        f"检测成功：{success_count}\n"
                        f"检测失败：{failed_count}",
                        parse_mode="HTML",
                    )
                    return
            result = await document_service.analyze_document_nodes(
                file_name=document.file_name,
                file_type=file_type,
                content_bytes=content_bytes,
            )
            if not result:
                await processing_msg.edit_text("❌ 未能从文件中解析出有效内容")
                return
            message = (
                "📝 <b>节点文件分析完成</b>\n\n"
                + format_subscription_info(result)
                + "\n\n<i>💡 这是节点列表，不包含订阅流量信息。</i>"
            )
            try:
                await processing_msg.delete()
            except Exception as exc:
                logger.warning("删除进度消息失败: %s", exc)
            await update.message.reply_text(message, parse_mode="HTML")
        except Exception as exc:
            logger.error("文件处理失败: %s", exc)
            error_msg = str(exc)
            try:
                await processing_msg.edit_text(f"❌ 文件处理失败：{error_msg[:500]}{'...' if len(error_msg) > 500 else ''}")
            except Exception:
                await update.message.reply_text(f"❌ 文件处理失败：{error_msg[:500]}{'...' if len(error_msg) > 500 else ''}")

    return handle_document


def make_node_text_handler(*, document_service, format_subscription_info, logger):
    async def handle_node_text(update, context):
        del context
        processing_msg = await update.message.reply_text("📝 正在解析节点列表...")
        try:
            result = await document_service.analyze_node_text(text=update.message.text.strip())
            if not result:
                await processing_msg.edit_text("❌ 未能解析出有效节点")
                return
            message = format_subscription_info(result)
            try:
                await processing_msg.delete()
            except Exception as exc:
                logger.warning("删除进度消息失败: %s", exc)
            await update.message.reply_text(message, parse_mode="HTML")
        except Exception as exc:
            logger.error("节点文本解析失败: %s", exc)
            error_msg = str(exc)
            try:
                await processing_msg.edit_text(f"❌ 节点解析失败：{error_msg[:500]}{'...' if len(error_msg) > 500 else ''}")
            except Exception:
                await update.message.reply_text(f"❌ 节点解析失败：{error_msg[:500]}{'...' if len(error_msg) > 500 else ''}")

    return handle_node_text
