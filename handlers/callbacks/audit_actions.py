"""Owner-facing usage audit callback actions."""
from __future__ import annotations


def make_audit_callback_handler(
    *,
    is_owner,
    admin_service,
    build_usage_audit_keyboard,
    build_recent_activity_keyboard,
    build_owner_panel_keyboard,
    inline_keyboard_button,
    inline_keyboard_markup,
):
    async def handle_callback(update, context, action: str, hash_key: str) -> bool:
        del context
        query = update.callback_query
        if action not in {"audit", "audit_detail", "recent", "recent_detail", "panel"}:
            return False
        if not is_owner(update):
            await query.answer("只有 Owner 可以查看。", show_alert=True)
            return True

        if action == "panel":
            await query.answer("打开控制台...")
            target = hash_key
            if target == "root":
                await query.edit_message_text(
                    admin_service.build_owner_panel_text(),
                    parse_mode="HTML",
                    reply_markup=build_owner_panel_keyboard(section="root"),
                )
                return True
            if target in {"overview", "users", "maintenance", "maint_backup", "maint_access", "maint_ops"}:
                section = target
                keyboard_section = "maintenance" if target.startswith("maint_") else target
                await query.edit_message_text(
                    admin_service.build_owner_panel_section_text(section),
                    parse_mode="HTML",
                    reply_markup=build_owner_panel_keyboard(section=keyboard_section),
                )
                return True
            if target == "listusers":
                report = admin_service.build_user_list_message() or "当前暂无授权用户"
                await query.edit_message_text(
                    report,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=inline_keyboard_markup([[inline_keyboard_button("返回用户页", callback_data="panel:users")]]),
                )
                return True
            if target == "audit":
                report, paging = admin_service.build_usage_audit_report(mode="others", page=1, page_size=5)
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
            if target == "recentusers":
                report, paging = admin_service.build_recent_users_page(include_owner=False, page=1, page_size=5)
                await query.edit_message_text(
                    report,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=build_recent_activity_keyboard(
                        category="users",
                        scope=paging["scope"],
                        page=paging["page"],
                        total_pages=paging["total_pages"],
                        record_count=len(paging["records"]),
                    ),
                )
                return True
            if target == "recentexports":
                report, paging = admin_service.build_recent_exports_page(include_owner=False, page=1, page_size=5)
                await query.edit_message_text(
                    report,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=build_recent_activity_keyboard(
                        category="exports",
                        scope=paging["scope"],
                        page=paging["page"],
                        total_pages=paging["total_pages"],
                        record_count=len(paging["records"]),
                    ),
                )
                return True
            if target == "globallist":
                report = admin_service.build_globallist_report() or "当前除了 Owner 外暂无其他用户订阅"
                await query.edit_message_text(
                    report,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=inline_keyboard_markup([[inline_keyboard_button("返回总览页", callback_data="panel:overview")]]),
                )
                return True
            await query.edit_message_text(
                admin_service.build_owner_panel_text(),
                parse_mode="HTML",
                reply_markup=build_owner_panel_keyboard(section="root"),
            )
            return True

        if action == "audit":
            await query.answer("加载审计记录...")
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

        if action == "recent":
            await query.answer("加载最近记录...")
            try:
                category, scope, page_str = hash_key.split(":", 2)
                page = int(page_str)
            except ValueError:
                category, scope, page = "users", "others", 1
            include_owner = scope == "all"
            if category == "exports":
                report, paging = admin_service.build_recent_exports_page(include_owner=include_owner, page=page, page_size=5)
            else:
                report, paging = admin_service.build_recent_users_page(include_owner=include_owner, page=page, page_size=5)
            await query.edit_message_text(
                report,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=build_recent_activity_keyboard(
                    category=category,
                    scope=paging["scope"],
                    page=paging["page"],
                    total_pages=paging["total_pages"],
                    record_count=len(paging["records"]),
                ),
            )
            return True

        if action == "recent_detail":
            await query.answer("读取详情信息...")
            try:
                category, scope, page_str, index_str = hash_key.split("|", 3)
                page = int(page_str)
                detail_index = int(index_str)
            except ValueError:
                await query.answer("数据异常", show_alert=True)
                return True
            include_owner = scope == "all"
            if category == "exports":
                detail_text = admin_service.build_recent_exports_detail(include_owner=include_owner, page=page, page_size=5, detail_index=detail_index)
                _, paging = admin_service.build_recent_exports_page(include_owner=include_owner, page=page, page_size=5)
            else:
                detail_text = admin_service.build_recent_users_detail(include_owner=include_owner, page=page, page_size=5, detail_index=detail_index)
                _, paging = admin_service.build_recent_users_page(include_owner=include_owner, page=page, page_size=5)
            await query.edit_message_text(
                detail_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=inline_keyboard_markup(
                    [
                        [inline_keyboard_button("返回列表", callback_data=f"recent:{category}:{scope}:{page}")],
                        [
                            inline_keyboard_button("上一页", callback_data=f"recent:{category}:{scope}:{max(1, page - 1)}"),
                            inline_keyboard_button("下一页", callback_data=f"recent:{category}:{scope}:{min(paging['total_pages'], page + 1)}"),
                        ],
                        [inline_keyboard_button("返回控制台", callback_data="panel:root")],
                    ]
                ),
            )
            return True

        try:
            await query.answer("读取详情信息...")
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
                    [inline_keyboard_button("返回控制台", callback_data="panel:root")],
                ]
            ),
        )
        return True

    return handle_callback
