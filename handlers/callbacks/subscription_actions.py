"""Subscription callback actions extracted from the legacy button handler."""
from __future__ import annotations

import hashlib
import html
import time

from handlers.callbacks.audit_actions import make_audit_callback_handler
from handlers.callbacks.cache_actions import make_cache_callback_handler


def make_subscription_callback_handler(
    *,
    get_storage,
    is_owner,
    get_parser,
    format_subscription_info,
    make_sub_keyboard,
    cleanup_url_cache,
    url_cache,
    tag_forbidden_msg,
    tag_exists_alert,
    confirm_delete_label,
    inline_keyboard_button,
    inline_keyboard_markup,
    get_short_callback_data,
    latency_tester,
    usage_audit_service,
    admin_service,
    export_cache_service,
    build_usage_audit_keyboard,
    build_recent_activity_keyboard,
    build_owner_panel_keyboard,
    format_subscription_compact,
    schedule_result_collapse,
    logger,
):
    audit_callback_handler = make_audit_callback_handler(
        is_owner=is_owner,
        admin_service=admin_service,
        build_usage_audit_keyboard=build_usage_audit_keyboard,
        build_recent_activity_keyboard=build_recent_activity_keyboard,
        build_owner_panel_keyboard=build_owner_panel_keyboard,
        inline_keyboard_button=inline_keyboard_button,
        inline_keyboard_markup=inline_keyboard_markup,
    )
    cache_callback_handler = make_cache_callback_handler(
        get_storage=get_storage,
        is_owner=is_owner,
        export_cache_service=export_cache_service,
        usage_audit_service=usage_audit_service,
    )

    async def handle_callback(update, context, action: str, hash_key: str) -> bool:
        query = update.callback_query
        store = get_storage()
        operator_uid = update.effective_user.id
        owner_mode = is_owner(update)

        handled = await audit_callback_handler(update, context, action, hash_key)
        if handled:
            return True

        if action == "tag_apply":
            await query.answer("处理标签中...")
            parts = hash_key.split("|", 1)
            if len(parts) != 2:
                await query.answer("数据异常", show_alert=True)
                return True
            url_hash, tag = parts[0], parts[1]
            cleanup_url_cache()
            cache_entry = url_cache.get(url_hash)
            url = cache_entry.get("url") if cache_entry else None
            if not url:
                await query.answer("操作已过期，请重新发起", show_alert=True)
                return True
            if store.add_tag(url, tag, operator_uid=operator_uid, require_owner=not owner_mode):
                await query.edit_message_text(f"✅ 已添加标签：{tag}\n订阅：{store.get_all().get(url, {}).get('name', url)}")
            else:
                sub = store.get_all().get(url, {})
                sub_owner = sub.get("owner_uid", 0)
                if sub_owner and sub_owner != operator_uid and not owner_mode:
                    await query.answer("无权修改他人的订阅标签", show_alert=True)
                    await query.edit_message_text(tag_forbidden_msg)
                else:
                    await query.answer(tag_exists_alert, show_alert=True)
                    await query.edit_message_text(f"ℹ️ 标签“{tag}”已存在，无需重复添加")
            return True

        if action == "tag_new":
            await query.answer("准备新建标签...")
            cleanup_url_cache()
            cache_entry = url_cache.get(hash_key)
            url = cache_entry.get("url") if cache_entry else None
            if not url:
                await query.answer("操作已过期，请重新发起", show_alert=True)
                return True
            sub = store.get_all().get(url, {})
            if sub.get("owner_uid", 0) not in {0, operator_uid} and not owner_mode:
                await query.answer("无权修改他人的订阅标签", show_alert=True)
                return True
            await query.edit_message_text(f"请发送新标签名称：\n订阅: {sub.get('name', url)}")
            context.user_data["pending_tag_url"] = url
            return True

        cleanup_url_cache()
        url = url_cache.get(hash_key, {}).get("url")
        if not url:
            for candidate in store.get_all().keys():
                if hashlib.md5(candidate.encode("utf-8")).hexdigest()[:16] == hash_key:
                    url = candidate
                    url_cache[hash_key] = {"url": url, "ts": time.time()}
                    break

        handled = await cache_callback_handler(update, context, action, url)
        if handled:
            return True

        if action in {"recheck", "delete", "del_confirm", "del_cancel", "tag", "ping"} and not url:
            await query.answer("操作已过期，请重新发送链接后再试", show_alert=True)
            return True

        if action == "recheck":
            await query.answer("正在发起重新检测，请稍候...")
            await query.edit_message_text("⏳ 正在重新检测...")
            try:
                parser_instance = await get_parser()
                result = await parser_instance.parse(url)
                owner_uid = store.get_all().get(url, {}).get("owner_uid", 0)
                store.add_or_update(url, result, user_id=owner_uid)
                export_cache_service.save_subscription_cache(owner_uid=owner_uid, source=url, result=result)
                compact_info = dict(result)
                cache_status = export_cache_service.get_cache_status(owner_uid=owner_uid, source=url)
                if cache_status:
                    compact_info["_cache_expires_at"] = cache_status.get("expires_at")
                    compact_info["_cache_remaining_text"] = cache_status.get("remaining_text")
                    compact_info["_cache_last_exported_at"] = cache_status.get("last_exported_at")
                usage_audit_service.log_check(user=update.effective_user, urls=[url], source="按钮重检")
                reply_markup = make_sub_keyboard(url)
                await query.edit_message_text(
                    format_subscription_info(result, url),
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                schedule_result_collapse(
                    context=context,
                    message=query.message,
                    info=compact_info,
                    url=url,
                    formatter=format_subscription_compact,
                    reply_markup=reply_markup,
                )
            except Exception as exc:
                await query.edit_message_text(f"❌ 重新检测失败：{exc}")
            return True

        if action == "delete":
            await query.answer("请确认是否删除")
            sub_name = store.get_all().get(url, {}).get("name", url)
            keyboard = [[
                inline_keyboard_button(confirm_delete_label, callback_data=get_short_callback_data("del_confirm", url)),
                inline_keyboard_button("🔙 返回", callback_data=get_short_callback_data("recheck", url)),
            ]]
            await query.edit_message_text(
                f"❓ <b>确定删除订阅吗？</b>\n\n名称：{html.escape(sub_name)}\n此操作不可撤销。",
                parse_mode="HTML",
                reply_markup=inline_keyboard_markup(keyboard),
            )
            return True

        if action == "del_confirm":
            await query.answer("执行删除操作...")
            if store.remove(url, operator_uid=operator_uid, require_owner=not owner_mode):
                await query.edit_message_text("🗑️ <b>订阅已永久移除</b>", parse_mode="HTML")
            else:
                await query.edit_message_text("❌ 删除失败：无权限或记录已不存在")
            return True

        if action == "del_cancel":
            await query.answer("操作已取消")
            await query.edit_message_text("🗳️ <b>已取消删除操作</b>", parse_mode="HTML")
            return True

        if action == "ping":
            await query.answer("开始连通性测试，请耐心等待...")
            await query.edit_message_text("⚡ 正在执行真实节点并发测速，请稍候...")
            try:
                parser_instance = await get_parser()
                result = await parser_instance.parse(url)
                nodes = result.get("_raw_nodes", [])
                if not nodes:
                    await query.edit_message_text("❌ 当前格式不支持直接获取节点列表测速。")
                    return True
                alive_count, total_count, alive_nodes = await latency_tester.ping_all_nodes(nodes, concurrency=20)
                ping_report = (
                    "<b>⚡ 测速报告</b>\n"
                    f"总计: {total_count} | ✅ 存活: {alive_count} | ❌ 失效: {total_count - alive_count}\n"
                    + "—" * 20
                    + "\n"
                )
                if alive_nodes:
                    ping_report += "\n<b>🏆 Top 5 最快节点:</b>\n"
                    for index, node in enumerate(alive_nodes[:5], start=1):
                        ping_report += f"{index}. {html.escape(node['name'])} - <code>{node['latency']}ms</code>\n"
                await query.message.reply_text(ping_report, parse_mode="HTML")
                await query.message.delete()
            except Exception as exc:
                logger.error("测速过程中发生错误: %s", exc)
                await query.edit_message_text(f"❌ 测速过程中发生错误: {exc}")
            return True

        if action == "tag":
            await query.answer("正在加载标签选项...")
            sub = store.get_all().get(url, {})
            sub_owner = sub.get("owner_uid", 0)
            if sub_owner and sub_owner != operator_uid and not owner_mode:
                await query.answer("无权修改他人的订阅标签", show_alert=True)
                return True
            user_subs = store.get_by_user(operator_uid)
            existing_tags = sorted({tag for data in user_subs.values() for tag in data.get("tags", [])})
            sub_name = sub.get("name", url)
            if existing_tags:
                tag_buttons = []
                row = []
                for tag in existing_tags:
                    callback = f"tag_apply:{hash_key}|{tag}"
                    if len(callback) <= 64:
                        row.append(inline_keyboard_button(f"🏷 {tag}", callback_data=callback))
                    if len(row) == 2:
                        tag_buttons.append(row)
                        row = []
                if row:
                    tag_buttons.append(row)
                tag_buttons.append([inline_keyboard_button("✏️ 新建标签", callback_data=get_short_callback_data("tag_new", url))])
                await query.edit_message_text(
                    f"为 <b>{html.escape(sub_name)}</b> 选择或新建标签：",
                    parse_mode="HTML",
                    reply_markup=inline_keyboard_markup(tag_buttons),
                )
            else:
                await query.edit_message_text(f"请发送标签名称：\n订阅: {sub_name}")
                context.user_data["pending_tag_url"] = url
            return True

        return False

    return handle_callback
