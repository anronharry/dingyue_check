"""Subscription URL text handlers."""
from __future__ import annotations



def make_subscription_handler(
    *,
    is_valid_url,
    document_service,
    format_subscription_info,
    make_sub_keyboard,
    usage_audit_service,
    logger,
):
    async def handle_subscription(update, context):
        del context
        text = update.message.text.strip()
        candidate_urls = [line.strip() for line in text.split("\n") if line.strip()]

        valid_urls = []
        for url in candidate_urls:
            if not is_valid_url(url):
                await update.message.reply_text(f"❌ 无效的订阅链接：{url[:50]}...")
                continue
            valid_urls.append(url)

        if not valid_urls:
            return

        usage_audit_service.log_check(
            user=update.effective_user,
            urls=valid_urls,
            source="文本订阅链接",
        )

        processing_msg = await update.message.reply_text(f"⏳ 正在解析订阅，共 {len(valid_urls)} 个...")
        try:
            results = await document_service.parse_subscription_urls(
                subscription_urls=valid_urls,
                owner_uid=update.effective_user.id,
            )
            try:
                await processing_msg.delete()
            except Exception as exc:
                logger.warning("删除进度消息失败: %s", exc)

            for item in results:
                if item["status"] == "success":
                    await update.message.reply_text(
                        format_subscription_info(item["data"], item["url"]),
                        parse_mode="HTML",
                        reply_markup=make_sub_keyboard(item["url"]),
                    )
                else:
                    error_msg = str(item["error"])
                    if len(error_msg) > 500:
                        error_msg = error_msg[:500] + "..."
                    await update.message.reply_text(f"❌ 订阅解析失败：{error_msg}")
        except Exception as exc:
            logger.error("订阅解析失败: %s", exc)
            error_msg = str(exc)
            if len(error_msg) > 500:
                error_msg = error_msg[:500] + "..."
            try:
                await processing_msg.edit_text(f"❌ 订阅解析失败：{error_msg}")
            except Exception:
                await update.message.reply_text(f"❌ 订阅解析失败：{error_msg}")

    return handle_subscription
