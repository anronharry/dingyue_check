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
    inline_keyboard_button=None,
    inline_keyboard_markup=None,
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

        if context.user_data.get("awaiting_owner_broadcast"):
            if not is_owner(update):
                context.user_data.pop("awaiting_owner_broadcast", None)
                context.user_data.pop("pending_owner_broadcast_text", None)
                await update.message.reply_text("❌ 仅管理员可以发送广播。")
                return
            content = (update.message.text or "").strip()
            if not content:
                await update.message.reply_text("❌ 广播内容不能为空，请重新发送。")
                return
            context.user_data["pending_owner_broadcast_text"] = content
            context.user_data.pop("awaiting_owner_broadcast", None)
            if inline_keyboard_button and inline_keyboard_markup:
                keyboard = inline_keyboard_markup(
                    [
                        [inline_keyboard_button("发送广播", callback_data="panel:maint_broadcast_send")],
                        [
                            inline_keyboard_button("重新编辑", callback_data="panel:maint_broadcast_edit"),
                            inline_keyboard_button("取消", callback_data="panel:maint_broadcast_cancel"),
                        ],
                    ]
                )
            else:
                keyboard = None
            await update.message.reply_text(
                "广播草稿已保存，请使用下方按钮发送或继续编辑。",
                reply_markup=keyboard,
            )
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
