"""Cache export and delete callback actions."""
from __future__ import annotations

import os


def make_cache_callback_handler(*, get_storage, is_owner, export_cache_service):
    async def handle_callback(update, context, action: str, url: str | None) -> bool:
        del context
        if action not in {"export_yaml", "export_txt", "delete_cache"}:
            return False
        query = update.callback_query
        if not url:
            await query.answer("操作已过期，请重新发送链接后再试", show_alert=True)
            return True
        store = get_storage()
        operator_uid = update.effective_user.id
        owner_mode = is_owner(update)
        sub = store.get_all().get(url, {})
        if action in {"export_yaml", "export_txt"}:
            await query.answer("正在从缓存读取并生成文件，请稍候...")
            fmt = "yaml" if action == "export_yaml" else "txt"
            path, error = export_cache_service.resolve_export_path(
                owner_uid=sub.get("owner_uid", 0),
                source=url,
                fmt=fmt,
                requester_uid=operator_uid,
                is_owner=owner_mode,
            )
            if error or not path:
                await query.answer(error or "导出失败", show_alert=True)
                return True
            with open(path, "rb") as handle:
                await query.message.reply_document(
                    document=handle,
                    filename=os.path.basename(path),
                    caption=f"✅ 已从 48 小时缓存导出 {fmt.upper()}",
                )
            return True
        deleted, error = export_cache_service.delete_entry(
            owner_uid=sub.get("owner_uid", 0),
            source=url,
            requester_uid=operator_uid,
            is_owner=owner_mode,
        )
        if not deleted:
            await query.answer(error or "删除失败", show_alert=True)
            return True
        await query.answer("缓存已删除")
        return True

    return handle_callback
