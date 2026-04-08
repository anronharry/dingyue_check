"""Cache export and delete callback actions."""
from __future__ import annotations

import os
import time


ERROR_CACHE_MISSING = "cache_missing"
ERROR_FORBIDDEN = "forbidden"
ERROR_FILE_MISSING = "file_missing"
ERROR_UNKNOWN = "unknown"


def make_cache_callback_handler(*, get_storage, is_owner, export_cache_service, usage_audit_service):
    in_flight: dict[tuple[int, str, str], float] = {}
    recent_actions: dict[tuple[int, str, str], float] = {}

    def classify_export_error(error: str | None, fmt: str) -> tuple[str, str]:
        if error == ERROR_CACHE_MISSING:
            return (
                f"{fmt.upper()} 缓存不存在或已过期，请重新发送订阅链接后再试。",
                "缓存不存在或已过期",
            )
        if error == ERROR_FORBIDDEN:
            return (
                f"当前无权导出这个 {fmt.upper()} 缓存。",
                "无权导出该缓存",
            )
        if error == ERROR_FILE_MISSING:
            return (
                f"{fmt.upper()} 缓存文件缺失，请重新生成后再试。",
                "缓存文件缺失，请重新生成",
            )
        return (
            f"{fmt.upper()} 导出失败，请稍后重试。",
            "导出失败，请稍后重试",
        )

    def classify_delete_error(error: str | None) -> tuple[str, str]:
        if error == ERROR_CACHE_MISSING:
            return "缓存不存在或已被清理。", "缓存不存在或已被清理"
        if error == ERROR_FORBIDDEN:
            return "当前无权删除这个缓存。", "无权删除该缓存"
        return "删除缓存失败，请稍后重试。", "删除缓存失败，请稍后重试"

    def resolve_owner_uid(*, sub: dict, source: str) -> int:
        owner_uid = int(sub.get("owner_uid", 0) or 0)
        if owner_uid:
            return owner_uid
        fallback_owner_uid = export_cache_service.find_owner_uid_by_source(source=source)
        return int(fallback_owner_uid or 0)

    async def schedule_cleanup(context, message, delay: int = 8) -> None:
        if not context or not getattr(context, "job_queue", None):
            return

        async def _cleanup(_):
            try:
                await message.delete()
            except Exception:
                pass

        context.job_queue.run_once(_cleanup, delay)

    async def handle_callback(update, context, action: str, url: str | None) -> bool:
        if action not in {"export_yaml", "export_txt", "delete_cache"}:
            return False

        query = update.callback_query
        if not url:
            await query.answer("操作已过期，请重新发送链接后再试。", show_alert=True)
            return True

        store = get_storage()
        operator_uid = update.effective_user.id
        owner_mode = is_owner(update)
        sub = store.get_all().get(url, {})
        owner_uid = resolve_owner_uid(sub=sub, source=url)
        action_key = (operator_uid, action, url)
        now = time.time()

        if recent_actions.get(action_key) and now - recent_actions[action_key] < 3:
            await query.answer("这个操作正在处理中，请稍后再试。")
            return True
        if in_flight.get(action_key) and now - in_flight[action_key] < 3:
            await query.answer("这个操作正在处理中，请稍后再试。")
            return True

        recent_actions[action_key] = now

        if action in {"export_yaml", "export_txt"}:
            in_flight[action_key] = now
            fmt = "yaml" if action == "export_yaml" else "txt"
            await query.answer(f"正在准备 {fmt.upper()}...")
            progress_msg = await query.message.reply_text(f"正在准备 {fmt.upper()} 文件，请稍候...")
            try:
                path, error = export_cache_service.resolve_export_path(
                    owner_uid=owner_uid,
                    source=url,
                    fmt=fmt,
                    requester_uid=operator_uid,
                    is_owner=owner_mode,
                )
                if error or not path:
                    detail_text, alert_text = classify_export_error(error, fmt)
                    await progress_msg.edit_text(f"失败：{detail_text}")
                    await schedule_cleanup(context, progress_msg)
                    await query.answer(alert_text, show_alert=True)
                    return True

                with open(path, "rb") as handle:
                    await query.message.reply_document(
                        document=handle,
                        filename=os.path.basename(path),
                        caption=f"已从 48 小时缓存导出 {fmt.upper()}",
                    )
                usage_audit_service.log_check(
                    user=update.effective_user,
                    urls=[url],
                    source=f"导出缓存:{fmt}",
                )
                await progress_msg.edit_text(f"{fmt.upper()} 文件已发送")
                await schedule_cleanup(context, progress_msg)
                await query.answer(f"{fmt.upper()} 已发送")
                return True
            finally:
                in_flight.pop(action_key, None)

        in_flight[action_key] = now
        await query.answer("正在删除缓存...")
        deleted, error = export_cache_service.delete_entry(
            owner_uid=owner_uid,
            source=url,
            requester_uid=operator_uid,
            is_owner=owner_mode,
        )
        try:
            if not deleted:
                detail_text, alert_text = classify_delete_error(error)
                notice = await query.message.reply_text(detail_text)
                await schedule_cleanup(context, notice)
                await query.answer(alert_text, show_alert=True)
                return True

            reply_msg = await query.message.reply_text("48 小时导出缓存已删除")
            await schedule_cleanup(context, reply_msg)
            await query.answer("缓存已删除")
            return True
        finally:
            in_flight.pop(action_key, None)

    return handle_callback
