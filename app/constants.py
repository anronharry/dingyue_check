"""Shared application constants and user-facing copy."""


from __future__ import annotations
APP_TITLE = "GIPSON_CHECK - 订阅检测与转换机器人"
APP_FEATURES = "支持：订阅检测、格式转换、自动预警、深度检测"
APP_STARTUP = "启动 Telegram 订阅检测机器人 [V3 Async Native]..."

OWNER_ONLY_MSG = "❌ 仅 Owner 可使用此命令"
NO_PERMISSION_MSG = (
    "⛔️ <b>您无权使用此机器人。</b>\n\n"
    "如需获得使用权限，请私信联系：\n"
    '👉 <a href="https://t.me/qinhuaichuanbot">@qinhuaichuanbot</a>'
)
NO_PERMISSION_ALERT = "⛔️ 无权限，请联系 @qinhuaichuanbot"

TAG_FORBIDDEN_MSG = "❌ 添加标签失败：您无权修改他人的订阅"
TAG_EXISTS_ALERT = "该标签已存在，无需重复添加"

BTN_RECHECK = "🔄 重新检测"
BTN_TAG = "🏷️ 添加标签"
BTN_DELETE = "🗑️ 删除"
BTN_CONFIRM_DELETE = "✅ 确认删除"
