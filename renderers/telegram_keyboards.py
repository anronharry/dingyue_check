"""Telegram keyboard builders."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import BTN_DELETE, BTN_RECHECK, BTN_TAG


def build_subscription_keyboard(
    url: str,
    callback_data_builder,
    *,
    enable_latency_tester: bool = False,
    owner_mode: bool = False,
    compact_user_mode: bool = False,
    user_actions_expanded: bool = False,
) -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(BTN_RECHECK, callback_data=callback_data_builder("recheck", url))]
    if enable_latency_tester:
        row1.append(InlineKeyboardButton("节点测速", callback_data=callback_data_builder("ping", url)))
    if owner_mode:
        row1.append(InlineKeyboardButton(BTN_DELETE, callback_data=callback_data_builder("delete", url)))
        rows = [
            row1,
            [
                InlineKeyboardButton(BTN_TAG, callback_data=callback_data_builder("tag", url)),
                InlineKeyboardButton("导出 YAML", callback_data=callback_data_builder("export_yaml", url)),
                InlineKeyboardButton("导出 TXT", callback_data=callback_data_builder("export_txt", url)),
            ],
            [InlineKeyboardButton("删除缓存", callback_data=callback_data_builder("delete_cache", url))],
        ]
    else:
        rows = [row1]
        if compact_user_mode and not user_actions_expanded:
            rows.append([InlineKeyboardButton("更多操作", callback_data=callback_data_builder("more_ops", url))])
        else:
            rows.append(
                [
                    InlineKeyboardButton("导出 YAML", callback_data=callback_data_builder("export_yaml", url)),
                    InlineKeyboardButton("导出 TXT", callback_data=callback_data_builder("export_txt", url)),
                ]
            )
            if compact_user_mode:
                rows.append([InlineKeyboardButton("收起操作", callback_data=callback_data_builder("basic_ops", url))])
    return InlineKeyboardMarkup(rows)


def build_usage_audit_keyboard(
    *,
    mode: str,
    page: int,
    total_pages: int,
    record_count: int = 0,
    view: str = "time",
) -> InlineKeyboardMarkup:
    del record_count
    prev_page = page - 1 if page > 1 else 1
    next_page = page + 1 if page < total_pages else total_pages
    view = "user" if view == "user" else "time"
    switch_to = "time" if view == "user" else "user"
    switch_label = "🕒 按时间" if switch_to == "time" else "👤 按用户"
    rows = [
        [
            InlineKeyboardButton("👤 其他用户", callback_data=f"audit:others:{page}:{view}"),
            InlineKeyboardButton("Owner", callback_data=f"audit:owner:{page}:{view}"),
            InlineKeyboardButton("🧾 全部", callback_data=f"audit:all:{page}:{view}"),
        ],
        [InlineKeyboardButton(switch_label, callback_data=f"audit:{mode}:1:{switch_to}")],
        [
            InlineKeyboardButton("⬅️ 上一页", callback_data=f"audit:{mode}:{prev_page}:{view}"),
            InlineKeyboardButton("下一页 ➡️", callback_data=f"audit:{mode}:{next_page}:{view}"),
        ],
        [InlineKeyboardButton("🏠 返回控制台", callback_data="panel:root")],
    ]
    return InlineKeyboardMarkup(rows)


def build_recent_activity_keyboard(*, category: str, scope: str, page: int, total_pages: int, record_count: int = 0) -> InlineKeyboardMarkup:
    del record_count
    prev_page = page - 1 if page > 1 else 1
    next_page = page + 1 if page < total_pages else total_pages
    rows = [
        [
            InlineKeyboardButton("👤 非 Owner", callback_data=f"recent:{category}:others:{page}"),
            InlineKeyboardButton("🧾 全部", callback_data=f"recent:{category}:all:{page}"),
        ],
        [
            InlineKeyboardButton("⬅️ 上一页", callback_data=f"recent:{category}:{scope}:{prev_page}"),
            InlineKeyboardButton("下一页 ➡️", callback_data=f"recent:{category}:{scope}:{next_page}"),
        ],
        [InlineKeyboardButton("🏠 返回控制台", callback_data="panel:root")],
    ]
    return InlineKeyboardMarkup(rows)


def build_owner_panel_keyboard(*, section: str = "root") -> InlineKeyboardMarkup:
    if section == "overview":
        rows = [
            [
                InlineKeyboardButton("📒 使用审计", callback_data="panel:audit"),
                InlineKeyboardButton("📤 最近导出", callback_data="panel:recentexports"),
            ],
            [InlineKeyboardButton("🌐 全局订阅", callback_data="panel:globallist")],
            [InlineKeyboardButton("🏠 返回首页", callback_data="panel:root")],
        ]
    elif section == "users":
        rows = [
            [
                InlineKeyboardButton("🕒 最近活跃", callback_data="panel:recentusers"),
                InlineKeyboardButton("👥 授权名单", callback_data="panel:listusers"),
            ],
            [InlineKeyboardButton("🏠 返回首页", callback_data="panel:root")],
        ]
    elif section == "maintenance":
        rows = [
            [
                InlineKeyboardButton("💾 备份迁移", callback_data="panel:maint_backup"),
                InlineKeyboardButton("🔐 权限开关", callback_data="panel:maint_access"),
            ],
            [
                InlineKeyboardButton("🟢 开启公开访问", callback_data="panel:maint_access_enable"),
                InlineKeyboardButton("🔒 关闭公开访问", callback_data="panel:maint_access_disable"),
            ],
            [InlineKeyboardButton("📢 发布广播", callback_data="panel:maint_broadcast_start")],
            [InlineKeyboardButton("🔄 刷新命令菜单", callback_data="panel:maint_refresh_menu")],
            [InlineKeyboardButton("🏠 返回首页", callback_data="panel:root")],
        ]
    elif section == "maint_backup":
        rows = [
            [InlineKeyboardButton("📤 导出订阅 JSON", callback_data="panel:maint_export_json")],
            [InlineKeyboardButton("🗄️ 生成全量备份 ZIP", callback_data="panel:maint_backup_now")],
            [
                InlineKeyboardButton("📥 导入 JSON（上传）", callback_data="panel:maint_import_start"),
                InlineKeyboardButton("♻️ 恢复 ZIP（上传）", callback_data="panel:maint_restore_start"),
            ],
            [InlineKeyboardButton("🛠 返回维护页", callback_data="panel:maintenance")],
            [InlineKeyboardButton("🏠 返回首页", callback_data="panel:root")],
        ]
    elif section == "maint_ops":
        rows = [
            [
                InlineKeyboardButton("📒 使用审计", callback_data="panel:audit"),
                InlineKeyboardButton("🌐 全局订阅", callback_data="panel:globallist"),
            ],
            [
                InlineKeyboardButton("🕒 最近活跃", callback_data="panel:recentusers"),
                InlineKeyboardButton("📤 最近导出", callback_data="panel:recentexports"),
            ],
            [InlineKeyboardButton("🛠 返回维护页", callback_data="panel:maintenance")],
            [InlineKeyboardButton("🏠 返回首页", callback_data="panel:root")],
        ]
    else:
        rows = [
            [
                InlineKeyboardButton("📊 总览", callback_data="panel:overview"),
                InlineKeyboardButton("👥 用户", callback_data="panel:users"),
            ],
            [
                InlineKeyboardButton("📒 审计", callback_data="panel:audit"),
                InlineKeyboardButton("🛠 维护", callback_data="panel:maintenance"),
            ],
        ]
    return InlineKeyboardMarkup(rows)
