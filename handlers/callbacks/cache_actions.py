"""Cache export and delete callback actions."""
from __future__ import annotations

import os
import time


def make_cache_callback_handler(*, get_storage, is_owner, export_cache_service, usage_audit_service):
    in_flight: dict[tuple[int, str, str], float] = {}
    recent_actions: dict[tuple[int, str, str], float] = {}

    def classify_export_error(error: str | None, fmt: str) -> tuple[str, str]:
        if not error:
            return f"{fmt.upper()} 导出失败，请稍后重试", "导出失败，请稍后重试"
        if "缓存不存在或已过期" in error:
            return (
                f"{fmt.upper()} 缓存不存在或已过期，请重新发送订阅链接",
                "缓存已过期，请重新发送订阅链接",
            )
        if "无权导出" in error:
            return (
                f"当前无权导出这个 {fmt.upper()} 缓存",
                "无权导出该缓存",
            )
        if "缓存文件不存在" in error:
            return (
                f"{fmt.upper()} 缓存文件缺失，请重新生成后再试",
                "缓存文件缺失，请重新生成",
            )
        return (f"{fmt.upper()} 导出失败：{error}", error)

    async def handle_callback(update, context, action: str, url: str | None) -> bool:
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
        action_key = (operator_uid, action, url)
        now = time.time()
        last_triggered = recent_actions.get(action_key)
        if last_triggered and now - last_triggered < 3:
            await query.answer("这个操作正在处理中，请稍候再试")
            return True
        last_started = in_flight.get(action_key)
        if last_started and now - last_started < 3:
            await query.answer("这个操作正在处理中，请稍候再试")
            return True
        recent_actions[action_key] = now
        if action in {"export_yaml", "export_txt"}:
            in_flight[action_key] = now
            fmt = "yaml" if action == "export_yaml" else "txt"
            await query.answer(f"正在准备 {fmt.upper()}...")
            progress_msg = await query.message.reply_text(f"⏳ 正在准备 {fmt.upper()} 文件，请稍候...")
            try:
                path, error = export_cache_service.resolve_export_path(
                    owner_uid=sub.get("owner_uid", 0),
                    source=url,
                    fmt=fmt,
                    requester_uid=operator_uid,
                    is_owner=owner_mode,
                )
                if error or not path:
                    detail_text, alert_text = classify_export_error(error, fmt)
                    await progress_msg.edit_text(f"❌ {detail_text}")
                    if context and getattr(context, "job_queue", None):
                        async def _cleanup_failed_progress(_):
                            try:
                                await progress_msg.delete()
                            except Exception:
                                pass
                        context.job_queue.run_once(_cleanup_failed_progress, 8)
                    await query.answer(alert_text, show_alert=True)
                    return True
                with open(path, "rb") as handle:
                    await query.message.reply_document(
                        document=handle,
                        filename=os.path.basename(path),
                        caption=f"✅ 已从 48 小时缓存导出 {fmt.upper()}",
                    )
                usage_audit_service.log_check(
                    user=update.effective_user,
                    urls=[url],
                    source=f"导出缓存:{fmt}",
                )
                await progress_msg.edit_text(f"✅ {fmt.upper()} 文件已发送")
                if context and getattr(context, "job_queue", None):
                    async def _cleanup_progress(_):
                        try:
                            await progress_msg.delete()
                        except Exception:
                            pass
                    context.job_queue.run_once(_cleanup_progress, 8)
                await query.answer(f"{fmt.upper()} 已发送")
                return True
            finally:
                in_flight.pop(action_key, None)
        in_flight[action_key] = now
        deleted, error = export_cache_service.delete_entry(
            owner_uid=sub.get("owner_uid", 0),
            source=url,
            requester_uid=operator_uid,
            is_owner=owner_mode,
        )
        try:
            if not deleted:
                await query.answer(error or "删除失败", show_alert=True)
                return True
            await query.answer("缓存已删除")
            reply_msg = await query.message.reply_text("✅ 48 小时导出缓存已删除")
            if context and getattr(context, "job_queue", None):
                async def _cleanup_delete_notice(_):
                    try:
                        await reply_msg.delete()
                    except Exception:
                        pass
                context.job_queue.run_once(_cleanup_delete_notice, 8)
            return True
        finally:
            in_flight.pop(action_key, None)

    return handle_callback
