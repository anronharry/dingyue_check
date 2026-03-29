"""Owner-facing usage audit callback actions."""
from __future__ import annotations


def make_audit_callback_handler(*, is_owner, admin_service, build_usage_audit_keyboard, inline_keyboard_button, inline_keyboard_markup):
    async def handle_callback(update, context, action: str, hash_key: str) -> bool:
        del context
        query = update.callback_query
        if action not in {"audit", "audit_detail"}:
            return False
        if not is_owner(update):
            await query.answer("仅 Owner 可查看", show_alert=True)
            return True
        if action == "audit":
            try:
                mode, page_str = hash_key.split(":", 1)
                page = int(page_str)
            except ValueError:
                mode, page = "others", 1
            report, paging = admin_service.build_usage_audit_report(mode=mode, page=page, page_size=5)
            await query.edit_message_text(
                report,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=build_usage_audit_keyboard(
                    mode=paging["mode"],
                    page=paging["page"],
                    total_pages=paging["total_pages"],
                    record_count=len(paging["records"]),
                ),
            )
            return True
        try:
            mode, page_str, index_str = hash_key.split("|", 2)
            page = int(page_str)
            detail_index = int(index_str)
        except ValueError:
            await query.answer("数据异常", show_alert=True)
            return True
        detail_text = admin_service.build_usage_audit_detail(mode=mode, page=page, page_size=5, detail_index=detail_index)
        _, paging = admin_service.build_usage_audit_report(mode=mode, page=page, page_size=5)
        await query.edit_message_text(
            detail_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_keyboard_markup(
                [
                    [inline_keyboard_button("返回审计列表", callback_data=f"audit:{mode}:{page}")],
                    [
                        inline_keyboard_button("上一页", callback_data=f"audit:{mode}:{max(1, page - 1)}"),
                        inline_keyboard_button("下一页", callback_data=f"audit:{mode}:{min(paging['total_pages'], page + 1)}"),
                    ],
                ]
            ),
        )
        return True

    return handle_callback
