"""
Telegram 订阅检测与转换机器人 - 异步版本。

当前文件只负责运行时装配、共享资源初始化和启动/关闭流程，
业务主链路已经迁移到 handlers/ 与 services/。
"""

import asyncio
import hashlib
import logging
import os
import sys
import time
from collections import OrderedDict

from dotenv import load_dotenv
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ContextTypes

from app.bootstrap import build_application, log_startup_banner, register_handlers, run_polling
from app.constants import (
    BTN_CONFIRM_DELETE,
    BTN_DELETE,
    BTN_RECHECK,
    BTN_TAG,
    OWNER_ONLY_MSG,
    TAG_EXISTS_ALERT,
    TAG_FORBIDDEN_MSG,
)
from app.settings import AppSettings
from core.access_control import UserManager
from core.access_state import AccessStateStore
from core.node_tester import _async_run_node_latency_test
from core.parser import SubscriptionParser
from core.storage_enhanced import SubscriptionStorage
from core.workspace_manager import WorkspaceManager
from handlers.callbacks.router import make_button_callback
from handlers.callbacks.subscription_actions import make_subscription_callback_handler
from handlers.commands.admin import (
    make_add_user_command,
    make_broadcast_command,
    make_checkall_command,
    make_del_user_command,
    make_delete_command,
    make_export_command,
    make_globallist_command,
    make_import_command,
    make_list_users_command,
    make_refresh_menu_command,
    make_set_public_access_command,
    make_usage_audit_command,
)
from handlers.commands.basic import make_help_command, make_start_command, make_stats_command
from handlers.commands.conversion import make_deepcheck_command, make_to_txt_command, make_to_yaml_command
from handlers.commands.subscriptions import make_check_command, make_list_command
from handlers.messages.documents import make_document_handler, make_node_text_handler
from handlers.messages.router import make_message_handler
from handlers.messages.subscriptions import make_subscription_handler
from jobs.cache_cleanup_job import run_cache_cleanup
from renderers.telegram_keyboards import build_subscription_keyboard
from services.access_service import AccessService
from services.admin_service import AdminService
from services.conversion_service import ConversionService
from services.document_service import DocumentService
from services.usage_audit_service import UsageAuditService
from utils.utils import InputDetector, format_subscription_info, format_traffic, is_valid_url

from features import latency_tester
from features import monitor
import config


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


load_dotenv()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

settings = AppSettings.from_env()
BOT_TOKEN = settings.bot_token
PROXY_PORT = settings.proxy_port
URL_CACHE_MAX_SIZE = settings.url_cache_max_size
URL_CACHE_TTL_SECONDS = settings.url_cache_ttl_seconds

ALLOWED_USER_IDS = settings.allowed_user_ids
access_state_store = AccessStateStore(os.path.join("data", "db", "access_state.json"))
usage_audit_service = UsageAuditService(os.path.join("data", "logs", "usage_audit.jsonl"))

if not ALLOWED_USER_IDS:
    logger.info("ALLOWED_USER_IDS 静态白名单为空，当前仅允许 Owner、动态授权用户或全员开放模式下的用户使用机器人。")
else:
    logger.info("用户白名单已启用，当前共有 %s 个 ENV 级静态授权用户。", len(ALLOWED_USER_IDS))

parser = None
storage = None
shared_session = None
ws_manager = WorkspaceManager("data")
user_manager = UserManager(os.path.join("data", "db", "users.json"), config.OWNER_ID)
access_service = AccessService(user_manager, access_state_store, ALLOWED_USER_IDS)

url_cache = OrderedDict()


def make_sub_keyboard(url: str) -> InlineKeyboardMarkup:
    return build_subscription_keyboard(
        url,
        get_short_callback_data,
        enable_latency_tester=config.ENABLE_LATENCY_TESTER,
    )


def _cleanup_url_cache():
    now = time.time()
    expired_keys = [key for key, value in url_cache.items() if now - value.get("ts", 0) > URL_CACHE_TTL_SECONDS]
    for key in expired_keys:
        url_cache.pop(key, None)

    while len(url_cache) > URL_CACHE_MAX_SIZE:
        url_cache.popitem(last=False)


async def _periodic_url_cache_cleanup(context: ContextTypes.DEFAULT_TYPE):
    await run_cache_cleanup(context, _cleanup_url_cache)


def get_short_callback_data(action, url):
    hash_key = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
    url_cache[hash_key] = {"url": url, "ts": time.time()}
    url_cache.move_to_end(hash_key)
    return f"{action}:{hash_key}"


async def get_parser():
    global parser, shared_session
    if shared_session is None:
        import aiohttp

        connector = aiohttp.TCPConnector(limit=100, limit_per_host=20)
        shared_session = aiohttp.ClientSession(connector=connector)

    if parser is None:
        parser = SubscriptionParser(proxy_port=PROXY_PORT, use_proxy=False, session=shared_session)
    return parser


async def _on_shutdown(application: Application):
    logger.info("正在关闭全局 HTTP Session 池...")
    del application

    global parser, shared_session
    if parser and hasattr(parser, "session") and parser.session:
        await parser.session.close()
        logger.info("SubscriptionParser 的 HTTP Session 已关闭。")
    elif shared_session:
        await shared_session.close()
        logger.info("共享 HTTP Session 已关闭。")

    from core.geo_service import GeoLocationService

    geo_client = GeoLocationService()
    if hasattr(geo_client, "close"):
        await geo_client.close()
        logger.info("GeoLocationService 的 HTTP Session 已关闭。")
    logger.info("后台 HTTP Session 池清理完毕。")


async def post_init(application: Application):
    try:
        user_commands = [
            BotCommand("start", "查看使用说明与快速入口"),
            BotCommand("check", "检测我的订阅状态"),
            BotCommand("list", "查看我的订阅列表"),
            BotCommand("to_yaml", "把 TXT 节点转为 YAML"),
            BotCommand("to_txt", "把 YAML 转为 TXT"),
            BotCommand("help", "查看详细帮助"),
            BotCommand("stats", "查看我的订阅统计"),
        ]
        await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

        owner_id = int(os.getenv("OWNER_ID", 0))
        if owner_id:
            owner_commands = user_commands + [
                BotCommand("listusers", "查看授权用户列表"),
                BotCommand("allowall", "开启全员可用模式"),
                BotCommand("denyall", "关闭全员可用模式"),
                BotCommand("usageaudit", "查看最近使用记录"),
                BotCommand("checkall", "全局检测所有用户订阅"),
                BotCommand("globallist", "查看全局订阅与链接"),
                BotCommand("broadcast", "向所有用户发送通知"),
            ]
            await application.bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=owner_id))
            logger.info("已成功为 Owner (%s) 注册专属管理菜单。", owner_id)

        if config.ENABLE_MONITOR:
            monitor.configure_monitor(application, get_storage(), get_parser, ws_manager)

        logger.info("快捷命令菜单（Bot Commands）已成功推送。")
    except Exception as exc:
        logger.error("注册快捷命令菜单失败: %s", exc)


def get_storage():
    global storage
    if storage is None:
        storage = SubscriptionStorage()
    return storage


def is_authorized(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    return access_service.is_authorized_uid(user.id)


def is_owner(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    return access_service.is_owner_uid(user.id)


async def _send_no_permission_msg(update: Update):
    msg = access_service.get_no_permission_message()
    try:
        if update.message:
            await update.message.reply_text(msg, parse_mode="HTML")
        elif update.callback_query:
            await update.callback_query.answer(access_service.get_no_permission_alert(), show_alert=True)
    except Exception as exc:
        logger.warning("发送权限拒绝提示失败: %s", exc)


def schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, user_msg=None, bot_msg=None, delay=30):
    async def _delete_job(cb_context: ContextTypes.DEFAULT_TYPE):
        del cb_context
        try:
            if user_msg:
                await user_msg.delete()
        except Exception:
            pass
        try:
            if bot_msg:
                await bot_msg.delete()
        except Exception:
            pass

    if context.job_queue:
        context.job_queue.run_once(_delete_job, delay)


start_command = make_start_command(
    is_authorized=is_authorized,
    is_owner=is_owner,
    send_no_permission_msg=_send_no_permission_msg,
    logger=logger,
)
help_command = make_help_command(
    is_authorized=is_authorized,
    is_owner=is_owner,
    send_no_permission_msg=_send_no_permission_msg,
    schedule_auto_delete=schedule_auto_delete,
)
stats_command = make_stats_command(
    is_authorized=is_authorized,
    is_owner=is_owner,
    send_no_permission_msg=_send_no_permission_msg,
    get_storage=get_storage,
    schedule_auto_delete=schedule_auto_delete,
)
check_command = make_check_command(
    is_authorized=is_authorized,
    send_no_permission_msg=_send_no_permission_msg,
    get_storage=get_storage,
    get_parser=get_parser,
    format_traffic=format_traffic,
    make_sub_keyboard=make_sub_keyboard,
    usage_audit_service=usage_audit_service,
    logger=logger,
)
list_command = make_list_command(
    is_authorized=is_authorized,
    send_no_permission_msg=_send_no_permission_msg,
    get_storage=get_storage,
    get_short_callback_data=get_short_callback_data,
    button_labels={
        "recheck": BTN_RECHECK,
        "tag": BTN_TAG,
        "delete": BTN_DELETE,
    },
    telegram_inline_button=InlineKeyboardButton,
    telegram_inline_markup=InlineKeyboardMarkup,
    schedule_auto_delete=schedule_auto_delete,
)

subscription_callback_handler = make_subscription_callback_handler(
    get_storage=get_storage,
    is_owner=is_owner,
    get_parser=get_parser,
    format_subscription_info=format_subscription_info,
    make_sub_keyboard=make_sub_keyboard,
    cleanup_url_cache=_cleanup_url_cache,
    url_cache=url_cache,
    tag_forbidden_msg=TAG_FORBIDDEN_MSG,
    tag_exists_alert=TAG_EXISTS_ALERT,
    confirm_delete_label=BTN_CONFIRM_DELETE,
    inline_keyboard_button=InlineKeyboardButton,
    inline_keyboard_markup=InlineKeyboardMarkup,
    get_short_callback_data=get_short_callback_data,
    latency_tester=latency_tester,
    usage_audit_service=usage_audit_service,
    logger=logger,
)

admin_service = AdminService(
    get_storage=get_storage,
    user_manager=user_manager,
    owner_id=config.OWNER_ID,
    format_traffic=format_traffic,
    access_service=access_service,
    usage_audit_service=usage_audit_service,
)
checkall_command = make_checkall_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    get_storage=get_storage,
    get_parser=get_parser,
    make_sub_keyboard=make_sub_keyboard,
    admin_service=admin_service,
    usage_audit_service=usage_audit_service,
    schedule_auto_delete=schedule_auto_delete,
)
broadcast_command = make_broadcast_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    user_manager=user_manager,
    schedule_auto_delete=schedule_auto_delete,
    logger=logger,
)
allowall_command = make_set_public_access_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    access_service=access_service,
    enabled=True,
    schedule_auto_delete=schedule_auto_delete,
)
denyall_command = make_set_public_access_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    access_service=access_service,
    enabled=False,
    schedule_auto_delete=schedule_auto_delete,
)
usageaudit_command = make_usage_audit_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    admin_service=admin_service,
    schedule_auto_delete=schedule_auto_delete,
)
delete_command = make_delete_command(
    is_authorized=is_authorized,
    send_no_permission_msg=_send_no_permission_msg,
    get_storage=get_storage,
    is_owner=is_owner,
    confirm_delete_label=BTN_CONFIRM_DELETE,
    get_short_callback_data=get_short_callback_data,
    inline_keyboard_button=InlineKeyboardButton,
    inline_keyboard_markup=InlineKeyboardMarkup,
    schedule_auto_delete=schedule_auto_delete,
)
export_command = make_export_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    get_storage=get_storage,
    schedule_auto_delete=schedule_auto_delete,
    admin_service=admin_service,
)
import_command = make_import_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    schedule_auto_delete=schedule_auto_delete,
)
add_user_command = make_add_user_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    user_manager=user_manager,
    schedule_auto_delete=schedule_auto_delete,
)
del_user_command = make_del_user_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    user_manager=user_manager,
    owner_id=config.OWNER_ID,
    schedule_auto_delete=schedule_auto_delete,
)
list_users_command = make_list_users_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    admin_service=admin_service,
    schedule_auto_delete=schedule_auto_delete,
)
refresh_menu_command = make_refresh_menu_command(
    is_owner=is_owner,
    post_init=post_init,
)
globallist_command = make_globallist_command(
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    admin_service=admin_service,
    schedule_auto_delete=schedule_auto_delete,
)

conversion_service = ConversionService(
    workspace_manager=ws_manager,
    latency_runner=_async_run_node_latency_test,
)
document_service = DocumentService(
    get_parser=get_parser,
    get_storage=get_storage,
    logger=logger,
)
to_yaml_command = make_to_yaml_command(
    is_authorized=is_authorized,
    send_no_permission_msg=_send_no_permission_msg,
    conversion_service=conversion_service,
)
to_txt_command = make_to_txt_command(
    is_authorized=is_authorized,
    send_no_permission_msg=_send_no_permission_msg,
    conversion_service=conversion_service,
)
deepcheck_command = make_deepcheck_command(
    is_authorized=is_authorized,
    send_no_permission_msg=_send_no_permission_msg,
    conversion_service=conversion_service,
    logger=logger,
)
handle_document = make_document_handler(
    is_authorized=is_authorized,
    send_no_permission_msg=_send_no_permission_msg,
    input_detector=InputDetector,
    is_owner=is_owner,
    owner_only_msg=OWNER_ONLY_MSG,
    document_service=document_service,
    format_subscription_info=format_subscription_info,
    make_sub_keyboard=make_sub_keyboard,
    usage_audit_service=usage_audit_service,
    logger=logger,
)
handle_node_text = make_node_text_handler(
    document_service=document_service,
    format_subscription_info=format_subscription_info,
    logger=logger,
)
handle_subscription = make_subscription_handler(
    is_valid_url=is_valid_url,
    document_service=document_service,
    format_subscription_info=format_subscription_info,
    make_sub_keyboard=make_sub_keyboard,
    usage_audit_service=usage_audit_service,
    logger=logger,
)
handle_message = make_message_handler(
    is_authorized=is_authorized,
    send_no_permission_msg=_send_no_permission_msg,
    is_owner=is_owner,
    get_storage=get_storage,
    input_detector=InputDetector,
    handle_document=handle_document,
    handle_subscription=handle_subscription,
    handle_node_text=handle_node_text,
    tag_forbidden_msg=TAG_FORBIDDEN_MSG,
)
button_callback = make_button_callback(
    is_authorized=is_authorized,
    no_permission_alert=access_service.get_no_permission_alert(),
    subscription_callback_handler=subscription_callback_handler,
)


def main():
    if not BOT_TOKEN:
        logger.error("错误: 未设置 TELEGRAM_BOT_TOKEN")
        return

    log_startup_banner()

    application = build_application(BOT_TOKEN, post_init, _on_shutdown)
    register_handlers(
        application,
        {
            "start": start_command,
            "help": help_command,
            "check": check_command,
            "checkall": checkall_command,
            "allowall": allowall_command,
            "denyall": denyall_command,
            "list": list_command,
            "stats": stats_command,
            "export": export_command,
            "import": import_command,
            "adduser": add_user_command,
            "deluser": del_user_command,
            "listusers": list_users_command,
            "usageaudit": usageaudit_command,
            "globallist": globallist_command,
            "broadcast": broadcast_command,
            "to_yaml": to_yaml_command,
            "to_txt": to_txt_command,
            "deepcheck": deepcheck_command,
            "delete": delete_command,
            "refresh_menu": refresh_menu_command,
            "button_callback": button_callback,
            "handle_document": handle_document,
            "handle_message": handle_message,
        },
    )

    if application.job_queue:
        application.job_queue.run_repeating(_periodic_url_cache_cleanup, interval=600, first=600)

    config.print_config_summary()

    if config.OWNER_ID > 0:
        migrated = get_storage().migrate_subscriptions(config.OWNER_ID)
        if migrated:
            logger.info("历史数据迁移完成，%s 条订阅已归属到 Owner (UID: %s)。", migrated, config.OWNER_ID)

    if not config.ENABLE_MONITOR:
        logger.info("定时监控已关闭（ENABLE_MONITOR=False）。")

    run_polling(application)


if __name__ == "__main__":
    main()
