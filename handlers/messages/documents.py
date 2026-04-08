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
    export_cache_service,
    format_subscription_info,
    format_subscription_compact,
    format_node_analysis_compact,
    make_sub_keyboard,
    schedule_result_collapse,
    backup_service,
    usage_audit_service,
    logger,
):
    async def handle_document(update, context):
        document = update.message.document

        if context.user_data.get("awaiting_restore") and document.file_name.lower().endswith(".zip"):
            if document.file_size and document.file_size > MAX_RESTORE_ZIP_SIZE_BYTES:
                await update.message.reply_text("Backup ZIP is too large (max 20MB).")
                return

            processing_msg = await update.message.reply_text("Restoring backup...")
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
                await processing_msg.edit_text(f"Backup restored. Restored files: {len(restored)}")
            except Exception as exc:
                logger.error("Backup restore failed: %s", exc)
                await processing_msg.edit_text(f"Backup restore failed: {exc}")
            finally:
                try:
                    if os.path.exists(temp_zip_path):
                        os.remove(temp_zip_path)
                except OSError:
                    logger.warning("Failed to remove temporary restore file: %s", temp_zip_path)
            return

        if not is_authorized(update):
            await send_no_permission_msg(update)
            return

        file_type = input_detector.detect_file_type(document.file_name)
        if file_type == "unknown":
            await update.message.reply_text("Unsupported file type. Please upload TXT/YAML, or run /import before JSON.")
            return

        if file_type in {"txt", "yaml"}:
            progress_text = f"Received {file_type.upper()} file. Parsing nodes and running quick checks..."
        else:
            progress_text = f"Received {file_type.upper()} file. Parsing content..."
        processing_msg = await update.message.reply_text(progress_text)

        if document.file_size and document.file_size > MAX_DOCUMENT_SIZE_BYTES:
            await processing_msg.edit_text("File too large: exceeds 5MB limit.")
            return

        try:
            telegram_file = await document.get_file()
            content_bytes = bytes(await telegram_file.download_as_bytearray())

            if file_type == "json":
                if not is_owner(update):
                    await processing_msg.edit_text(owner_only_msg)
                    return
                if not context.user_data.get("awaiting_import"):
                    await processing_msg.edit_text("Please run /import first, then upload the exported JSON file.")
                    return
                imported_count = await document_service.import_json(content_bytes=content_bytes)
                context.user_data.pop("awaiting_import", None)
                await processing_msg.edit_text(f"Import completed. Imported subscriptions: {imported_count}")
                return

            if file_type == "txt":
                subscription_urls = document_service.extract_subscription_urls(content_bytes=content_bytes)
                if subscription_urls:
                    if usage_audit_service:
                        usage_audit_service.log_check(
                            user=update.effective_user,
                            urls=subscription_urls,
                            source=f"document_import:{document.file_name}",
                        )
                    await processing_msg.edit_text(
                        f"Detected {len(subscription_urls)} subscription links. Checking and saving..."
                    )
                    results = await document_service.parse_subscription_urls(
                        subscription_urls=subscription_urls,
                        owner_uid=update.effective_user.id,
                    )
                    try:
                        await processing_msg.delete()
                    except Exception as exc:
                        logger.warning("Failed to delete progress message: %s", exc)

                    for item in sorted(results, key=lambda row: row["index"]):
                        if item["status"] == "success":
                            message = f"<b>Subscription {item['index']} Result</b>\n\n{format_subscription_info(item['data'], item['url'])}"
                            reply_markup = make_sub_keyboard(item["url"])
                            compact_info = dict(item["data"])
                            cache_status = export_cache_service.get_cache_status(
                                owner_uid=update.effective_user.id,
                                source=item["url"],
                            )
                            if cache_status:
                                compact_info["_cache_expires_at"] = cache_status.get("expires_at")
                                compact_info["_cache_remaining_text"] = cache_status.get("remaining_text")
                                compact_info["_cache_last_exported_at"] = cache_status.get("last_exported_at")
                            sent_msg = await update.message.reply_text(
                                message,
                                parse_mode="HTML",
                                reply_markup=reply_markup,
                            )
                            schedule_result_collapse(
                                context=context,
                                message=sent_msg,
                                info=compact_info,
                                url=item["url"],
                                formatter=format_subscription_compact,
                                reply_markup=reply_markup,
                            )
                        else:
                            await update.message.reply_text(
                                f"Subscription {item['index']} failed\nReason: {item['error']}",
                            )

                    success_count = sum(1 for item in results if item["status"] == "success")
                    failed_count = sum(1 for item in results if item["status"] == "failed")
                    await update.message.reply_text(
                        "<b>Subscription File Processing Completed</b>\n\n"
                        f"Detected: {len(subscription_urls)}\n"
                        f"Success: {success_count}\n"
                        f"Failed: {failed_count}",
                        parse_mode="HTML",
                    )
                    return

            result = await document_service.analyze_document_nodes(
                file_name=document.file_name,
                file_type=file_type,
                content_bytes=content_bytes,
                owner_uid=update.effective_user.id,
            )
            if not result:
                await processing_msg.edit_text("No valid content parsed from file.")
                return

            message = (
                "<b>Node File Analysis Completed</b>\n\n"
                + format_subscription_info(result)
                + "\n\n<i>This is a node list and does not include subscription traffic or expiry metadata.</i>"
            )
            try:
                await processing_msg.delete()
            except Exception as exc:
                logger.warning("Failed to delete progress message: %s", exc)
            sent_msg = await update.message.reply_text(message, parse_mode="HTML")
            schedule_result_collapse(
                context=context,
                message=sent_msg,
                info=result,
                url=None,
                formatter=format_node_analysis_compact,
                reply_markup=None,
            )
        except Exception as exc:
            logger.error("Document processing failed: %s", exc)
            error_msg = str(exc)
            short_error = f"{error_msg[:500]}{'...' if len(error_msg) > 500 else ''}"
            try:
                await processing_msg.edit_text(f"Document processing failed: {short_error}")
            except Exception:
                await update.message.reply_text(f"Document processing failed: {short_error}")

    return handle_document


def make_node_text_handler(*, document_service, format_subscription_info, format_node_analysis_compact, schedule_result_collapse, logger):
    async def handle_node_text(update, context):
        processing_msg = await update.message.reply_text("Parsing node list and running quick checks...")
        try:
            result = await document_service.analyze_node_text(text=update.message.text.strip())
            if not result:
                await processing_msg.edit_text("No valid nodes parsed.")
                return
            message = format_subscription_info(result)
            try:
                await processing_msg.delete()
            except Exception as exc:
                logger.warning("Failed to delete progress message: %s", exc)
            sent_msg = await update.message.reply_text(message, parse_mode="HTML")
            schedule_result_collapse(
                context=context,
                message=sent_msg,
                info=result,
                url=None,
                formatter=format_node_analysis_compact,
                reply_markup=None,
            )
        except Exception as exc:
            logger.error("Node text parsing failed: %s", exc)
            error_msg = str(exc)
            short_error = f"{error_msg[:500]}{'...' if len(error_msg) > 500 else ''}"
            try:
                await processing_msg.edit_text(f"Node parsing failed: {short_error}")
            except Exception:
                await update.message.reply_text(f"Node parsing failed: {short_error}")

    return handle_node_text
