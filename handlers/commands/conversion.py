"""Conversion and deep-check command handlers."""
from __future__ import annotations


def make_to_yaml_command(*, is_authorized, send_no_permission_msg, conversion_service):
    async def to_yaml_command(update, context):
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return
        if not update.message.reply_to_message or not update.message.reply_to_message.document:
            await update.message.reply_text("❌ 请回复包含节点列表的 TXT 文件消息使用此命令")
            return
        document = update.message.reply_to_message.document
        if not document.file_name.lower().endswith(".txt"):
            await update.message.reply_text("❌ 仅支持对 .txt 文件进行转换")
            return
        processing_msg = await update.message.reply_text("⏳ 正在转换文件格式（TXT → YAML）...")
        try:
            telegram_file = await document.get_file()
            content_bytes = bytes(await telegram_file.download_as_bytearray())
            result = conversion_service.convert_txt_bytes_to_yaml(
                file_name=document.file_name,
                content_bytes=content_bytes,
                owner_uid=update.effective_user.id,
            )
            if not result["ok"]:
                await processing_msg.edit_text(f"❌ 转换失败：{result['error']}")
                return
            with open(result["output_path"], "rb") as handle:
                await update.message.reply_document(document=handle, filename=result["output_name"], caption="✅ 转换成功 (Clash YAML 格式)")
            await processing_msg.delete()
        except Exception as exc:
            await processing_msg.edit_text(f"❌ 转换失败：{exc}")

    return to_yaml_command


def make_to_txt_command(*, is_authorized, send_no_permission_msg, conversion_service):
    async def to_txt_command(update, context):
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return
        if not update.message.reply_to_message or not update.message.reply_to_message.document:
            await update.message.reply_text("❌ 请回复包含 Clash 配置的 YAML 文件消息使用此命令")
            return
        document = update.message.reply_to_message.document
        if not document.file_name.lower().endswith((".yaml", ".yml")):
            await update.message.reply_text("❌ 仅支持对 .yaml/.yml 文件进行转换")
            return
        processing_msg = await update.message.reply_text("⏳ 正在转换文件格式（YAML → TXT）...")
        try:
            telegram_file = await document.get_file()
            content_bytes = bytes(await telegram_file.download_as_bytearray())
            result = conversion_service.convert_yaml_bytes_to_txt(
                file_name=document.file_name,
                content_bytes=content_bytes,
                owner_uid=update.effective_user.id,
            )
            if not result["ok"]:
                await processing_msg.edit_text(f"❌ 转换失败：{result['error']}")
                return
            with open(result["output_path"], "rb") as handle:
                await update.message.reply_document(document=handle, filename=result["output_name"], caption="✅ 转换成功 (明文 TXT 格式)")
            await processing_msg.delete()
        except Exception as exc:
            await processing_msg.edit_text(f"❌ 转换失败：{exc}")

    return to_txt_command


def make_deepcheck_command(*, is_authorized, send_no_permission_msg, conversion_service, logger):
    async def deepcheck_command(update, context):
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return
        if not update.message.reply_to_message or not update.message.reply_to_message.document:
            await update.message.reply_text("❌ 请回复包含节点或订阅的 TXT/YAML 文件消息使用此命令")
            return
        document = update.message.reply_to_message.document
        telegram_file = await document.get_file()
        content_bytes = bytes(await telegram_file.download_as_bytearray())
        processing_msg = await update.message.reply_text("⏳ 正在初始化深度检测引擎 (Mihomo)...")

        async def status_callback(message: str):
            try:
                if processing_msg.text == message:
                    return
                await processing_msg.edit_text(message)
            except Exception:
                return

        try:
            result = await conversion_service.run_deepcheck(
                file_name=document.file_name,
                content_bytes=content_bytes,
                status_callback=status_callback,
                owner_uid=update.effective_user.id,
            )
            if result["output_path"]:
                with open(result["output_path"], "rb") as handle:
                    await update.message.reply_document(
                        document=handle,
                        filename=result["output_name"],
                        caption="✅ 深度检测完成，已导出可用节点。",
                    )
                await processing_msg.delete()
            else:
                await processing_msg.edit_text("✅ 深度检测完成，未生成导出文件。")
        except Exception as exc:
            logger.error("深度检测失败: %s", exc)
            await processing_msg.edit_text(f"❌ 深度检测失败：{exc}")

    return deepcheck_command
