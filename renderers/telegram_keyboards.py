"""Telegram keyboard builders."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import BTN_DELETE, BTN_RECHECK, BTN_TAG


def build_subscription_keyboard(url: str, callback_data_builder, *, enable_latency_tester: bool = False) -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(BTN_RECHECK, callback_data=callback_data_builder("recheck", url))]
    if enable_latency_tester:
        row1.append(InlineKeyboardButton("⚡ 节点测速", callback_data=callback_data_builder("ping", url)))
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
        detail_row = []
        for index in range(record_count):
            detail_row.append(InlineKeyboardButton(f"详情{index + 1}", callback_data=f"audit_detail:{mode}|{page}|{index}"))
        rows.append(detail_row)
    rows.append(
        [
            InlineKeyboardButton("上一页", callback_data=f"audit:{mode}:{prev_page}"),
            InlineKeyboardButton("下一页", callback_data=f"audit:{mode}:{next_page}"),
        ]
    )
    return InlineKeyboardMarkup(rows)
