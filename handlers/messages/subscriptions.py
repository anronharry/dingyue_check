"""Subscription URL text handlers."""
from __future__ import annotations


def make_subscription_handler(
    *,
    is_valid_url,
    is_owner,
    document_service,
    format_subscription_info,
    make_sub_keyboard,
    usage_audit_service,
    logger,
):
    def _make_sub_keyboard_safe(*, url: str, owner_mode: bool, operator_uid: int):
        try:
            return make_sub_keyboard(url, operator_uid=operator_uid, owner_mode=owner_mode)
        except TypeError:
            return make_sub_keyboard(url, owner_mode=owner_mode)

    async def handle_subscription(update, context):
        del context
        reply_to_message_id = getattr(update.message, "message_id", None)
        reply_kwargs = {"reply_to_message_id": reply_to_message_id} if reply_to_message_id else {}
        text = update.message.text.strip()
        candidate_urls = [line.strip() for line in text.split("\n") if line.strip()]
        valid_urls = []

        for url in candidate_urls:
            if not is_valid_url(url):
                await update.message.reply_text(f"❌ 无效的订阅链接：{url[:80]}", **reply_kwargs)
                continue
            valid_urls.append(url)

        if not valid_urls:
            return

        usage_audit_service.log_check(user=update.effective_user, urls=valid_urls, source="文本订阅链接")
        processing_msg = await update.message.reply_text(
            f"🚀 正在解析订阅，共 {len(valid_urls)} 个...",
            **reply_kwargs,
        )

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
                    reply_markup = _make_sub_keyboard_safe(
                        url=item["url"],
                        operator_uid=update.effective_user.id,
                        owner_mode=is_owner(update),
                    )
                    await update.message.reply_text(
                        format_subscription_info(item["data"], item["url"]),
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                        **reply_kwargs,
                    )
                    continue

                error_msg = str(item.get("error", "未知错误"))
                await update.message.reply_text(
                    f"❌ 订阅解析失败：{error_msg[:500]}{'...' if len(error_msg) > 500 else ''}",
                    **reply_kwargs,
                )
        except Exception as exc:
            logger.error("订阅解析失败: %s", exc)
            error_msg = str(exc)
            short_error = f"{error_msg[:500]}{'...' if len(error_msg) > 500 else ''}"
            try:
                await processing_msg.edit_text(f"❌ 订阅解析失败：{short_error}")
            except Exception:
                await update.message.reply_text(f"❌ 订阅解析失败：{short_error}", **reply_kwargs)

    return handle_subscription
