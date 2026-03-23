"""Message routing handlers for plain text user input."""
from __future__ import annotations



def make_message_handler(
    *,
    is_authorized,
    send_no_permission_msg,
    is_owner,
    get_storage,
    input_detector,
    handle_document,
    handle_subscription,
    handle_node_text,
    tag_forbidden_msg,
):
    async def handle_message(update, context):
        if not is_authorized(update):
            await send_no_permission_msg(update)
            return

        if "pending_tag_url" in context.user_data:
            url = context.user_data["pending_tag_url"]
            tag = update.message.text.strip()
            operator_uid = update.effective_user.id
            owner_mode = is_owner(update)
            store = get_storage()
            if store.add_tag(url, tag, operator_uid=operator_uid, require_owner=not owner_mode):
                await update.message.reply_text(f"✅ 已添加标签：{tag}")
            else:
                sub = store.get_all().get(url, {})
                sub_owner = sub.get("owner_uid", 0)
                if sub_owner and sub_owner != operator_uid and not owner_mode:
                    await update.message.reply_text(tag_forbidden_msg)
                else:
                    await update.message.reply_text("❌ 添加标签失败")
            del context.user_data["pending_tag_url"]
            return

        input_type = input_detector.detect_message_type(update)
        if input_type == "file":
            await handle_document(update, context)
        elif input_type == "url":
            await handle_subscription(update, context)
        elif input_type == "node_text":
            await handle_node_text(update, context)
        else:
            await update.message.reply_text(
                "❌ 无法识别输入内容\n\n"
                "请发送：\n"
                "• 订阅链接（http / https）\n"
                "• 上传 TXT / YAML 文件\n"
                "• 粘贴节点列表（vmess://、ss:// 等）"
            )

    return handle_message
