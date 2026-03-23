"""Telegram keyboard builders."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import BTN_DELETE, BTN_RECHECK, BTN_TAG


def build_subscription_keyboard(
    url: str,
    callback_data_builder,
    *,
    enable_latency_tester: bool = False,
) -> InlineKeyboardMarkup:
    row1 = [
        InlineKeyboardButton(BTN_RECHECK, callback_data=callback_data_builder("recheck", url)),
    ]
    if enable_latency_tester:
        row1.append(InlineKeyboardButton("⚡ 节点测速", callback_data=callback_data_builder("ping", url)))
    row1.append(InlineKeyboardButton(BTN_DELETE, callback_data=callback_data_builder("delete", url)))
    return InlineKeyboardMarkup(
        [
            row1,
            [InlineKeyboardButton(BTN_TAG, callback_data=callback_data_builder("tag", url))],
        ]
    )
