"""Subscription callback actions extracted from the legacy button handler."""
from __future__ import annotations

import html

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
    access_service=None,
    post_init=None,
    user_manager=None,
    backup_service=None,
    subscription_check_service=None,
    alert_preference_service=None,
):
    del format_subscription_compact, schedule_result_collapse

    audit_callback_handler = make_audit_callback_handler(
        is_owner=is_owner,
        admin_service=admin_service,
        access_service=access_service,
        post_init=post_init,
        user_manager=user_manager,
        get_storage=get_storage,
        backup_service=backup_service,
        logger=logger,
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

    def _safe_user_error(exc: Exception, *, fallback: str = "操作失败，请稍后重试。") -> str:
        msg = str(exc or "").strip().splitlines()[0]
        if not msg:
            return fallback
        if len(msg) > 120:
            msg = msg[:120] + "..."
        return msg

    def _build_callback(action: str, url: str, operator_uid: int) -> str:
        try:
            return get_short_callback_data(action, url, operator_uid=operator_uid)
        except TypeError:
            return get_short_callback_data(action, url)

    def _make_sub_keyboard_safe(
        *,
        url: str,
        operator_uid: int,
        owner_mode: bool,
        user_actions_expanded: bool = False,
    ):
        try:
            return make_sub_keyboard(
                url,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
                user_actions_expanded=user_actions_expanded,
            )
        except TypeError:
            try:
                return make_sub_keyboard(url, owner_mode=owner_mode, user_actions_expanded=user_actions_expanded)
            except TypeError:
                return make_sub_keyboard(url, owner_mode=owner_mode)

    def _resolve_url(hash_key: str, *, operator_uid: int) -> str | None:
        cleanup_url_cache()
        cache_entry = url_cache.get(hash_key, {})
        cache_uid = int(cache_entry.get("uid", 0) or 0)
        if cache_uid and cache_uid != operator_uid:
            return None
        url = cache_entry.get("url")
        return url

    def _has_subscription_access(*, sub_owner_uid: int, operator_uid: int, owner_mode: bool) -> bool:
        if owner_mode:
            return True
        if sub_owner_uid <= 0:
            return True
        return sub_owner_uid == operator_uid

    async def _handle_tag_apply(query, context, *, store, operator_uid: int, owner_mode: bool, hash_key: str) -> bool:
        del context
        await query.answer("正在处理标签...")
        parts = hash_key.split("|", 1)
        if len(parts) != 2:
            await query.answer("数据异常", show_alert=True)
            return True
        url_hash, tag = parts
        cleanup_url_cache()
        cache_entry = url_cache.get(url_hash)
        cache_uid = int(cache_entry.get("uid", 0) or 0) if cache_entry else 0
        if cache_uid and cache_uid != operator_uid:
            await query.answer("操作已过期，请重新发起。", show_alert=True)
            return True
        url = cache_entry.get("url") if cache_entry else None
        if not url:
            await query.answer("操作已过期，请重新发起。", show_alert=True)
            return True

        if store.add_tag(url, tag, operator_uid=operator_uid, require_owner=not owner_mode):
            await query.edit_message_text(f"已添加标签：{tag}\n订阅：{store.get_all().get(url, {}).get('name', url)}")
            return True

        sub = store.get_all().get(url, {})
        sub_owner = sub.get("owner_uid", 0)
        if sub_owner and sub_owner != operator_uid and not owner_mode:
            await query.answer("无权修改他人的订阅标签", show_alert=True)
            await query.edit_message_text(tag_forbidden_msg)
            return True
        await query.answer(tag_exists_alert, show_alert=True)
        await query.edit_message_text(f"标签“{tag}”已存在，无需重复添加")
        return True

    async def _handle_tag_new(query, context, *, store, operator_uid: int, owner_mode: bool, hash_key: str) -> bool:
        await query.answer("准备新建标签...")
        cleanup_url_cache()
        cache_entry = url_cache.get(hash_key)
        cache_uid = int(cache_entry.get("uid", 0) or 0) if cache_entry else 0
        if cache_uid and cache_uid != operator_uid:
            await query.answer("操作已过期，请重新发起。", show_alert=True)
            return True
        url = cache_entry.get("url") if cache_entry else None
        if not url:
            await query.answer("操作已过期，请重新发起。", show_alert=True)
            return True
        sub = store.get_all().get(url, {})
        if sub.get("owner_uid", 0) not in {0, operator_uid} and not owner_mode:
            await query.answer("无权修改他人的订阅标签", show_alert=True)
            return True
        await query.edit_message_text(f"请发送新标签名称：\n订阅：{sub.get('name', url)}")
        context.user_data["pending_tag_url"] = url
        return True

    async def _handle_more_ops(query, _context, *, url: str, owner_mode: bool, operator_uid: int) -> bool:
        await query.answer("已展开导出功能，可下载 YAML/TXT")
        await query.edit_message_reply_markup(
            reply_markup=_make_sub_keyboard_safe(
                url=url,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
                user_actions_expanded=True,
            )
        )
        return True

    async def _handle_basic_ops(query, _context, *, url: str, owner_mode: bool, operator_uid: int) -> bool:
        await query.answer("已收起，仅保留核心操作")
        await query.edit_message_reply_markup(
            reply_markup=_make_sub_keyboard_safe(
                url=url,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
                user_actions_expanded=False,
            )
        )
        return True

    async def _handle_recheck(update, query, _context, *, store, url: str, owner_mode: bool, operator_uid: int) -> bool:
        await query.answer("🔄 正在重新检测，请稍候...")
        await query.edit_message_text("🔄 正在重新检测，请稍候...")
        try:
            sub = store.get_all().get(url, {})
            owner_uid = int(sub.get("owner_uid", 0) or 0)
            if not _has_subscription_access(
                sub_owner_uid=owner_uid,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
            ):
                await query.edit_message_text("无权操作他人的订阅。")
                return True
            if subscription_check_service:
                result = await subscription_check_service.parse_and_store(
                    url=url,
                    owner_uid=owner_uid,
                )
            else:
                parser_instance = await get_parser()
                result = await parser_instance.parse(url)
                store.add_or_update(url, result, user_id=owner_uid)
                export_cache_service.save_subscription_cache(owner_uid=owner_uid, source=url, result=result)
            usage_audit_service.log_check(user=update.effective_user, urls=[url], source="按钮重检")
            await query.edit_message_text(
                format_subscription_info(result, url),
                parse_mode="HTML",
                reply_markup=_make_sub_keyboard_safe(
                    url=url,
                    operator_uid=operator_uid,
                    owner_mode=owner_mode,
                ),
            )
        except Exception as exc:
            await query.edit_message_text(f"❌ 重新检测失败：{_safe_user_error(exc)}")
        return True

    async def _handle_delete_prompt(
        query,
        _context,
        *,
        store,
        url: str,
        operator_uid: int,
        owner_mode: bool,
    ) -> bool:
        await query.answer("请确认是否删除")
        sub = store.get_all().get(url, {})
        sub_owner = int(sub.get("owner_uid", 0) or 0)
        if not _has_subscription_access(
            sub_owner_uid=sub_owner,
            operator_uid=operator_uid,
            owner_mode=owner_mode,
        ):
            await query.edit_message_text("无权操作他人的订阅。")
            return True
        sub_name = sub.get("name", url)
        keyboard = [[
            inline_keyboard_button(
                confirm_delete_label,
                callback_data=_build_callback("del_confirm", url, operator_uid),
            ),
            inline_keyboard_button(
                "返回",
                callback_data=_build_callback("recheck", url, operator_uid),
            ),
        ]]
        await query.edit_message_text(
            f"<b>确定删除这个订阅吗？</b>\n\n名称：{html.escape(sub_name)}\n此操作不可撤销。",
            parse_mode="HTML",
            reply_markup=inline_keyboard_markup(keyboard),
        )
        return True

    async def _handle_delete_confirm(query, _context, *, store, url: str, operator_uid: int, owner_mode: bool) -> bool:
        await query.answer("正在执行删除...")
        if store.remove(url, operator_uid=operator_uid, require_owner=not owner_mode):
            await query.edit_message_text("<b>订阅已永久移除</b>", parse_mode="HTML")
        else:
            await query.edit_message_text("删除失败：无权限或记录已不存在")
        return True

    async def _handle_delete_cancel(query, _context) -> bool:
        await query.answer("已取消")
        await query.edit_message_text("<b>已取消删除操作</b>", parse_mode="HTML")
        return True

    async def _handle_ping(query, _context, *, store, url: str, operator_uid: int, owner_mode: bool) -> bool:
        await query.answer("🚀 开始连通性测试，请稍候...")
        await query.edit_message_text("🚀 正在执行并发测速，请稍候...")
        try:
            sub = store.get_all().get(url, {})
            sub_owner = int(sub.get("owner_uid", 0) or 0)
            if not _has_subscription_access(
                sub_owner_uid=sub_owner,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
            ):
                await query.edit_message_text("无权操作他人的订阅。")
                return True
            parser_instance = await get_parser()
            result = await parser_instance.parse(url)
            nodes = result.get("_normalized_nodes") or result.get("_raw_nodes", [])
            if not nodes:
                await query.edit_message_text("当前格式不支持直接获取节点列表测速。")
                return True
            alive_count, total_count, alive_nodes = await latency_tester.ping_all_nodes(nodes, concurrency=20)
            ping_report = (
                "<b>测速报告</b>\n"
                f"总计: {total_count} | 存活: {alive_count} | 失败: {total_count - alive_count}\n"
                "--------------------\n"
            )
            if alive_nodes:
                ping_report += "\n<b>Top 5 最快节点</b>\n"
                for index, node in enumerate(alive_nodes[:5], start=1):
                    ping_report += f"{index}. {html.escape(node['name'])} - <code>{node['latency']}ms</code>\n"
            await query.message.reply_text(ping_report, parse_mode="HTML")
            await query.message.delete()
        except Exception as exc:
            logger.error("测速过程中发生错误: %s", exc)
            await query.edit_message_text(f"❌ 测速失败：{_safe_user_error(exc)}")
        return True

    async def _handle_tag_select(query, context, *, store, url: str, operator_uid: int, owner_mode: bool, hash_key: str) -> bool:
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
                    row.append(inline_keyboard_button(f"标签 {tag}", callback_data=callback))
                if len(row) == 2:
                    tag_buttons.append(row)
                    row = []
            if row:
                tag_buttons.append(row)
            tag_buttons.append([
                inline_keyboard_button(
                    "新建标签",
                    callback_data=_build_callback("tag_new", url, operator_uid),
                )
            ])
            await query.edit_message_text(
                f"为 <b>{html.escape(sub_name)}</b> 选择或新建标签：",
                parse_mode="HTML",
                reply_markup=inline_keyboard_markup(tag_buttons),
            )
            return True
        await query.edit_message_text(f"请发送标签名称：\n订阅：{sub_name}")
        context.user_data["pending_tag_url"] = url
        return True

    async def _handle_mute_alerts(query, _context, *, operator_uid: int) -> bool:
        if not alert_preference_service:
            await query.answer("当前版本不支持该操作", show_alert=True)
            return True
        alert_preference_service.mute_user(operator_uid)
        await query.answer("已关闭预警提醒")
        try:
            await query.edit_message_reply_markup(
                reply_markup=inline_keyboard_markup(
                    [[inline_keyboard_button("🔔 恢复预警提醒", callback_data="unmute_alerts:on")]]
                )
            )
        except Exception:
            pass
        return True

    async def _handle_unmute_alerts(query, _context, *, operator_uid: int) -> bool:
        if not alert_preference_service:
            await query.answer("当前版本不支持该操作", show_alert=True)
            return True
        alert_preference_service.unmute_user(operator_uid)
        await query.answer("已恢复预警提醒")
        try:
            await query.edit_message_reply_markup(
                reply_markup=inline_keyboard_markup(
                    [[inline_keyboard_button("🔕 关闭预警提醒", callback_data="mute_alerts:off")]]
                )
            )
        except Exception:
            pass
        return True

    async def handle_callback(update, context, action: str, hash_key: str) -> bool:
        query = update.callback_query
        store = get_storage()
        operator_uid = update.effective_user.id
        owner_mode = is_owner(update)

        handled = await audit_callback_handler(update, context, action, hash_key)
        if handled:
            return True

        if action == "tag_apply":
            return await _handle_tag_apply(
                query,
                context,
                store=store,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
                hash_key=hash_key,
            )
        if action == "tag_new":
            return await _handle_tag_new(
                query,
                context,
                store=store,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
                hash_key=hash_key,
            )

        url = _resolve_url(hash_key, operator_uid=operator_uid)

        handled = await cache_callback_handler(update, context, action, url)
        if handled:
            return True

        requires_url = {"recheck", "delete", "del_confirm", "del_cancel", "tag", "ping", "more_ops", "basic_ops"}
        if action in requires_url and not url:
            await query.answer("操作已过期，请重新发送链接后再试。", show_alert=True)
            return True

        action_handlers = {
            "mute_alerts": lambda: _handle_mute_alerts(query, context, operator_uid=operator_uid),
            "unmute_alerts": lambda: _handle_unmute_alerts(query, context, operator_uid=operator_uid),
            "more_ops": lambda: _handle_more_ops(
                query,
                context,
                url=url,
                owner_mode=owner_mode,
                operator_uid=operator_uid,
            ),
            "basic_ops": lambda: _handle_basic_ops(
                query,
                context,
                url=url,
                owner_mode=owner_mode,
                operator_uid=operator_uid,
            ),
            "recheck": lambda: _handle_recheck(
                update,
                query,
                context,
                store=store,
                url=url,
                owner_mode=owner_mode,
                operator_uid=operator_uid,
            ),
            "delete": lambda: _handle_delete_prompt(
                query,
                context,
                store=store,
                url=url,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
            ),
            "del_confirm": lambda: _handle_delete_confirm(
                query,
                context,
                store=store,
                url=url,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
            ),
            "del_cancel": lambda: _handle_delete_cancel(query, context),
            "ping": lambda: _handle_ping(
                query,
                context,
                store=store,
                url=url,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
            ),
            "tag": lambda: _handle_tag_select(
                query,
                context,
                store=store,
                url=url,
                operator_uid=operator_uid,
                owner_mode=owner_mode,
                hash_key=hash_key,
            ),
        }
        handler = action_handlers.get(action)
        if handler is None:
            return False
        await handler()
        return True

    return handle_callback
