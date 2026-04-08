"""Telegram keyboard builders."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import BTN_DELETE, BTN_RECHECK, BTN_TAG


def build_subscription_keyboard(url: str, callback_data_builder, *, enable_latency_tester: bool = False) -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(BTN_RECHECK, callback_data=callback_data_builder("recheck", url))]
    if enable_latency_tester:
        row1.append(InlineKeyboardButton("节点测速", callback_data=callback_data_builder("ping", url)))
    row1.append(InlineKeyboardButton(BTN_DELETE, callback_data=callback_data_builder("delete", url)))
    return InlineKeyboardMarkup(
        [
            row1,
            [
                InlineKeyboardButton(BTN_TAG, callback_data=callback_data_builder("tag", url)),
                InlineKeyboardButton("导出 YAML", callback_data=callback_data_builder("export_yaml", url)),
                InlineKeyboardButton("导出 TXT", callback_data=callback_data_builder("export_txt", url)),
            ],
            [InlineKeyboardButton("删除缓存", callback_data=callback_data_builder("delete_cache", url))],
        ]
    )


def build_usage_audit_keyboard(*, mode: str, page: int, total_pages: int, record_count: int = 0) -> InlineKeyboardMarkup:
    prev_page = page - 1 if page > 1 else 1
    next_page = page + 1 if page < total_pages else total_pages
    rows = [
        [
            InlineKeyboardButton("其他用户", callback_data=f"audit:others:{page}"),
            InlineKeyboardButton("Owner", callback_data=f"audit:owner:{page}"),
            InlineKeyboardButton("全部", callback_data=f"audit:all:{page}"),
        ],
    ]
    if record_count:
        rows.append(
            [
                InlineKeyboardButton(f"详情{index + 1}", callback_data=f"audit_detail:{mode}|{page}|{index}")
                for index in range(record_count)
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("上一页", callback_data=f"audit:{mode}:{prev_page}"),
            InlineKeyboardButton("下一页", callback_data=f"audit:{mode}:{next_page}"),
        ]
    )
    rows.append([InlineKeyboardButton("返回控制台", callback_data="panel:root")])
    return InlineKeyboardMarkup(rows)


def build_recent_activity_keyboard(*, category: str, scope: str, page: int, total_pages: int, record_count: int = 0) -> InlineKeyboardMarkup:
    prev_page = page - 1 if page > 1 else 1
    next_page = page + 1 if page < total_pages else total_pages
    rows = [
        [
            InlineKeyboardButton("非 Owner", callback_data=f"recent:{category}:others:{page}"),
            InlineKeyboardButton("全部", callback_data=f"recent:{category}:all:{page}"),
        ],
    ]
    if record_count:
        rows.append(
            [
                InlineKeyboardButton(f"详情{index + 1}", callback_data=f"recent_detail:{category}|{scope}|{page}|{index}")
                for index in range(record_count)
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("上一页", callback_data=f"recent:{category}:{scope}:{prev_page}"),
            InlineKeyboardButton("下一页", callback_data=f"recent:{category}:{scope}:{next_page}"),
        ]
    )
    rows.append([InlineKeyboardButton("返回控制台", callback_data="panel:root")])
    return InlineKeyboardMarkup(rows)


def build_owner_panel_keyboard(*, section: str = "root") -> InlineKeyboardMarkup:
    if section == "overview":
        rows = [
            [
                InlineKeyboardButton("使用审计", callback_data="panel:audit"),
                InlineKeyboardButton("最近导出", callback_data="panel:recentexports"),
            ],
            [InlineKeyboardButton("全局订阅", callback_data="panel:globallist")],
            [InlineKeyboardButton("返回首页", callback_data="panel:root")],
        ]
    elif section == "users":
        rows = [
            [
                InlineKeyboardButton("最近活跃", callback_data="panel:recentusers"),
                InlineKeyboardButton("授权名单", callback_data="panel:listusers"),
            ],
            [InlineKeyboardButton("返回首页", callback_data="panel:root")],
        ]
    elif section == "maintenance":
        rows = [
            [
                InlineKeyboardButton("备份迁移", callback_data="panel:maint_backup"),
                InlineKeyboardButton("权限开关", callback_data="panel:maint_access"),
            ],
            [InlineKeyboardButton("维护命令", callback_data="panel:maint_ops")],
            [InlineKeyboardButton("返回首页", callback_data="panel:root")],
        ]
    else:
        rows = [
            [
                InlineKeyboardButton("总览", callback_data="panel:overview"),
                InlineKeyboardButton("用户", callback_data="panel:users"),
            ],
            [
                InlineKeyboardButton("审计", callback_data="panel:audit"),
                InlineKeyboardButton("维护", callback_data="panel:maintenance"),
            ],
        ]
    return InlineKeyboardMarkup(rows)
