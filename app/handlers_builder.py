"""Handler registration assembly."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.constants import BTN_CONFIRM_DELETE, BTN_DELETE, BTN_RECHECK, BTN_TAG, OWNER_ONLY_MSG, TAG_EXISTS_ALERT, TAG_FORBIDDEN_MSG
from app.runtime import Runtime
from features import latency_tester
from handlers.callbacks.router import make_button_callback
from handlers.callbacks.subscription_actions import make_subscription_callback_handler
from handlers.commands.admin import (
    make_add_user_command,
    make_backup_command,
    make_broadcast_command,
    make_checkall_command,
    make_del_user_command,
    make_delete_command,
    make_export_command,
    make_globallist_command,
    make_import_command,
    make_list_users_command,
    make_owner_panel_command,
    make_recent_exports_command,
    make_recent_users_command,
    make_refresh_menu_command,
    make_restore_command,
    make_set_public_access_command,
    make_usage_audit_command,
)
from handlers.commands.basic import make_help_command, make_start_command, make_stats_command
from handlers.commands.conversion import make_deepcheck_command, make_to_txt_command, make_to_yaml_command
from handlers.commands.subscriptions import make_check_command, make_list_command
from handlers.messages.documents import make_document_handler, make_node_text_handler
from handlers.messages.router import make_message_handler
from handlers.messages.subscriptions import make_subscription_handler
from renderers.formatters import format_subscription_compact, format_subscription_info
from renderers.telegram_keyboards import build_owner_panel_keyboard, build_recent_activity_keyboard, build_usage_audit_keyboard
from utils.utils import InputDetector, format_traffic, is_valid_url


def build_handlers(runtime: Runtime, *, post_init):
    handlers = {}
    handlers["start"] = make_start_command(is_authorized=runtime.is_authorized, is_owner=runtime.is_owner, send_no_permission_msg=runtime.send_no_permission_msg, logger=runtime.logger)
    handlers["help"] = make_help_command(is_authorized=runtime.is_authorized, is_owner=runtime.is_owner, send_no_permission_msg=runtime.send_no_permission_msg, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["stats"] = make_stats_command(is_authorized=runtime.is_authorized, is_owner=runtime.is_owner, send_no_permission_msg=runtime.send_no_permission_msg, get_storage=runtime.get_storage, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["check"] = make_check_command(
        is_authorized=runtime.is_authorized,
        is_owner=runtime.is_owner,
        send_no_permission_msg=runtime.send_no_permission_msg,
        get_storage=runtime.get_storage,
        get_parser=runtime.get_parser,
        format_traffic=format_traffic,
        make_sub_keyboard=runtime.make_sub_keyboard,
        usage_audit_service=runtime.usage_audit_service,
        logger=runtime.logger,
        subscription_check_service=runtime.subscription_check_service,
    )
    handlers["list"] = make_list_command(
        is_authorized=runtime.is_authorized,
        send_no_permission_msg=runtime.send_no_permission_msg,
        get_storage=runtime.get_storage,
        format_traffic=format_traffic,
        get_short_callback_data=runtime.get_short_callback_data,
        button_labels={"recheck": BTN_RECHECK, "tag": BTN_TAG, "delete": BTN_DELETE},
        telegram_inline_button=InlineKeyboardButton,
        telegram_inline_markup=InlineKeyboardMarkup,
        schedule_auto_delete=runtime.schedule_auto_delete,
    )
    handlers["checkall"] = make_checkall_command(
        is_owner=runtime.is_owner,
        owner_only_msg=OWNER_ONLY_MSG,
        get_storage=runtime.get_storage,
        get_parser=runtime.get_parser,
        make_sub_keyboard=runtime.make_sub_keyboard,
        admin_service=runtime.admin_service,
        usage_audit_service=runtime.usage_audit_service,
        schedule_auto_delete=runtime.schedule_auto_delete,
        subscription_check_service=runtime.subscription_check_service,
    )
    handlers["broadcast"] = make_broadcast_command(
        is_owner=runtime.is_owner,
        owner_only_msg=OWNER_ONLY_MSG,
        user_manager=runtime.user_manager,
        schedule_auto_delete=runtime.schedule_auto_delete,
        logger=runtime.logger,
    )
    handlers["allowall"] = make_set_public_access_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, access_service=runtime.access_service, enabled=True, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["denyall"] = make_set_public_access_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, access_service=runtime.access_service, enabled=False, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["usageaudit"] = make_usage_audit_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, admin_service=runtime.admin_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["delete"] = make_delete_command(
        is_authorized=runtime.is_authorized,
        send_no_permission_msg=runtime.send_no_permission_msg,
        get_storage=runtime.get_storage,
        is_owner=runtime.is_owner,
        confirm_delete_label=BTN_CONFIRM_DELETE,
        get_short_callback_data=runtime.get_short_callback_data,
        inline_keyboard_button=InlineKeyboardButton,
        inline_keyboard_markup=InlineKeyboardMarkup,
        schedule_auto_delete=runtime.schedule_auto_delete,
    )
    handlers["export"] = make_export_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, get_storage=runtime.get_storage, schedule_auto_delete=runtime.schedule_auto_delete, admin_service=runtime.admin_service)
    handlers["import"] = make_import_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["backup"] = make_backup_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, backup_service=runtime.backup_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["restore"] = make_restore_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["adduser"] = make_add_user_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, user_manager=runtime.user_manager, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["deluser"] = make_del_user_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, user_manager=runtime.user_manager, owner_id=runtime.admin_service.owner_id, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["listusers"] = make_list_users_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, admin_service=runtime.admin_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["ownerpanel"] = make_owner_panel_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, admin_service=runtime.admin_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["recentusers"] = make_recent_users_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, admin_service=runtime.admin_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["recentexports"] = make_recent_exports_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, admin_service=runtime.admin_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["refresh_menu"] = make_refresh_menu_command(is_owner=runtime.is_owner, post_init=post_init)
    handlers["globallist"] = make_globallist_command(is_owner=runtime.is_owner, owner_only_msg=OWNER_ONLY_MSG, admin_service=runtime.admin_service, schedule_auto_delete=runtime.schedule_auto_delete)
    handlers["to_yaml"] = make_to_yaml_command(is_authorized=runtime.is_authorized, send_no_permission_msg=runtime.send_no_permission_msg, conversion_service=runtime.conversion_service)
    handlers["to_txt"] = make_to_txt_command(is_authorized=runtime.is_authorized, send_no_permission_msg=runtime.send_no_permission_msg, conversion_service=runtime.conversion_service)
    handlers["deepcheck"] = make_deepcheck_command(is_authorized=runtime.is_authorized, send_no_permission_msg=runtime.send_no_permission_msg, conversion_service=runtime.conversion_service, logger=runtime.logger)
    handlers["handle_document"] = make_document_handler(
        is_authorized=runtime.is_authorized,
        send_no_permission_msg=runtime.send_no_permission_msg,
        input_detector=InputDetector,
        is_owner=runtime.is_owner,
        owner_only_msg=OWNER_ONLY_MSG,
        document_service=runtime.document_service,
        format_subscription_info=format_subscription_info,
        make_sub_keyboard=runtime.make_sub_keyboard,
        backup_service=runtime.backup_service,
        usage_audit_service=runtime.usage_audit_service,
        logger=runtime.logger,
    )
    handle_node_text = make_node_text_handler(
        document_service=runtime.document_service,
        format_subscription_info=format_subscription_info,
        logger=runtime.logger,
    )
    handle_subscription = make_subscription_handler(
        is_valid_url=is_valid_url,
        is_owner=runtime.is_owner,
        document_service=runtime.document_service,
        format_subscription_info=format_subscription_info,
        make_sub_keyboard=runtime.make_sub_keyboard,
        usage_audit_service=runtime.usage_audit_service,
        logger=runtime.logger,
    )
    handlers["handle_message"] = make_message_handler(
        is_authorized=runtime.is_authorized,
        send_no_permission_msg=runtime.send_no_permission_msg,
        is_owner=runtime.is_owner,
        get_storage=runtime.get_storage,
        input_detector=InputDetector,
        handle_document=handlers["handle_document"],
        handle_subscription=handle_subscription,
        handle_node_text=handle_node_text,
        tag_forbidden_msg=TAG_FORBIDDEN_MSG,
        inline_keyboard_button=InlineKeyboardButton,
        inline_keyboard_markup=InlineKeyboardMarkup,
    )
    subscription_callback_handler = make_subscription_callback_handler(
        get_storage=runtime.get_storage,
        is_owner=runtime.is_owner,
        get_parser=runtime.get_parser,
        format_subscription_info=format_subscription_info,
        make_sub_keyboard=runtime.make_sub_keyboard,
        cleanup_url_cache=runtime.cleanup_url_cache,
        url_cache=runtime.url_cache,
        tag_forbidden_msg=TAG_FORBIDDEN_MSG,
        tag_exists_alert=TAG_EXISTS_ALERT,
        confirm_delete_label=BTN_CONFIRM_DELETE,
        inline_keyboard_button=InlineKeyboardButton,
        inline_keyboard_markup=InlineKeyboardMarkup,
        get_short_callback_data=runtime.get_short_callback_data,
        latency_tester=latency_tester,
        usage_audit_service=runtime.usage_audit_service,
        admin_service=runtime.admin_service,
        export_cache_service=runtime.export_cache_service,
        build_usage_audit_keyboard=build_usage_audit_keyboard,
        build_recent_activity_keyboard=build_recent_activity_keyboard,
        build_owner_panel_keyboard=build_owner_panel_keyboard,
        format_subscription_compact=format_subscription_compact,
        schedule_result_collapse=runtime.schedule_result_collapse,
        logger=runtime.logger,
        access_service=runtime.access_service,
        post_init=post_init,
        user_manager=runtime.user_manager,
        backup_service=runtime.backup_service,
        subscription_check_service=runtime.subscription_check_service,
        alert_preference_service=runtime.alert_preference_service,
    )
    handlers["button_callback"] = make_button_callback(is_authorized=runtime.is_authorized, no_permission_alert=runtime.access_service.get_no_permission_alert(), subscription_callback_handler=subscription_callback_handler)

    sources = {
        "start": lambda u, c: "/start",
        "help": lambda u, c: "/help",
        "stats": lambda u, c: "/stats",
        "check": lambda u, c: "/check",
        "list": lambda u, c: "/list",
        "checkall": lambda u, c: "/checkall",
        "broadcast": lambda u, c: "/broadcast",
        "allowall": lambda u, c: "/allowall",
        "denyall": lambda u, c: "/denyall",
        "usageaudit": lambda u, c: "/usageaudit",
        "delete": lambda u, c: "/delete",
        "export": lambda u, c: "/export",
        "import": lambda u, c: "/import",
        "backup": lambda u, c: "/backup",
        "restore": lambda u, c: "/restore",
        "adduser": lambda u, c: "/adduser",
        "deluser": lambda u, c: "/deluser",
        "listusers": lambda u, c: "/listusers",
        "ownerpanel": lambda u, c: "/ownerpanel",
        "recentusers": lambda u, c: "/recentusers",
        "recentexports": lambda u, c: "/recentexports",
        "refresh_menu": lambda u, c: "/refresh_menu",
        "globallist": lambda u, c: "/globallist",
        "to_yaml": lambda u, c: "/to_yaml",
        "to_txt": lambda u, c: "/to_txt",
        "deepcheck": lambda u, c: "/deepcheck",
        "handle_document": lambda u, c: f"document:{getattr(u.message.document, 'file_name', 'unknown')}",
        "handle_message": lambda u, c: "text_message",
        "button_callback": lambda u, c: f"callback:{getattr(u.callback_query, 'data', 'unknown')}",
    }
    return {name: runtime.with_profile_tracking(handler, sources[name]) for name, handler in handlers.items()}
