"""Shared application constants and user-facing copy."""
from __future__ import annotations


APP_TITLE = "GIPSON_CHECK - Telegram Subscription Bot"
APP_FEATURES = "支持订阅检测、格式转换、自动预警、深度检查"
APP_STARTUP = "启动 Telegram 订阅检测机器人..."

OWNER_ONLY_MSG = "只有 Owner 可以使用此命令"
NO_PERMISSION_MSG = (
    "你当前没有权限使用这个机器人。\n\n"
    "如需开通权限，请联系维护者。"
)
NO_PERMISSION_ALERT = "无权限，请联系维护者"

TAG_FORBIDDEN_MSG = "添加标签失败：你无权修改其他人的订阅"
TAG_EXISTS_ALERT = "该标签已存在，无需重复添加"

BTN_RECHECK = "重新检测"
BTN_TAG = "添加标签"
BTN_DELETE = "删除"
BTN_CONFIRM_DELETE = "确认删除"
