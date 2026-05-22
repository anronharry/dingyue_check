"""Subscription callback actions extracted from the legacy button handler."""

from __future__ import annotations

from handlers.callbacks.audit_actions import make_audit_callback_handler
from handlers.callbacks.cache_actions import make_cache_callback_handler
from handlers.callbacks.subscription_ops import (
    handle_basic_ops,
    handle_delete_cancel,
    handle_delete_confirm,
    handle_delete_prompt,
    handle_more_ops,
    handle_mute_alerts,
    handle_recheck,
    handle_unmute_alerts,
)
from handlers.callbacks.subscription_ping import handle_ping
from handlers.callbacks.subscription_tags import handle_tag_apply, handle_tag_new, handle_tag_select
from handlers.callbacks.subscription_utils import SubscriptionCallbackDeps, resolve_url

URL_REQUIRED_ACTIONS = {
    "recheck",
    "delete",
    "del_confirm",
    "del_cancel",
    "tag",
    "ping",
    "more_ops",
    "basic_ops",
}


def make_button_callback(*, is_authorized, no_permission_alert, subscription_callback_handler):
    async def button_callback(update, context):
        query = update.callback_query
        try:
            action, hash_key = query.data.split(":", 1)
        except ValueError:
            await query.answer("数据异常", show_alert=True)
            return
        await query.answer()
        if action not in {
            "audit",
            "audit_detail",
            "recent",
            "recent_detail",
            "panel",
            "mute_alerts",
            "unmute_alerts",
        } and not is_authorized(update):
            await query.answer(no_permission_alert, show_alert=True)
            return
        handled = await subscription_callback_handler(update, context, action, hash_key)
        if not handled:
            await query.answer("未知操作", show_alert=True)

    return button_callback


def make_subscription_callback_handler(**kwargs):
    kwargs.pop("format_subscription_compact", None)
    kwargs.pop("schedule_result_collapse", None)
    deps = _build_deps(kwargs)
    audit_callback_handler = _build_audit_handler(kwargs)
    cache_callback_handler = make_cache_callback_handler(
        get_storage=kwargs["get_storage"],
        is_owner=kwargs["is_owner"],
        export_cache_service=kwargs["export_cache_service"],
        usage_audit_service=kwargs["usage_audit_service"],
    )

    async def handle_callback(update, context, action: str, hash_key: str) -> bool:
        return await _handle_callback(
            update,
            context,
            action,
            hash_key,
            deps,
            kwargs,
            audit_callback_handler,
            cache_callback_handler,
        )

    return handle_callback


def _build_deps(kwargs) -> SubscriptionCallbackDeps:
    return SubscriptionCallbackDeps(
        get_parser=kwargs["get_parser"],
        format_subscription_info=kwargs["format_subscription_info"],
        make_sub_keyboard=kwargs["make_sub_keyboard"],
        cleanup_url_cache=kwargs["cleanup_url_cache"],
        url_cache=kwargs["url_cache"],
        tag_forbidden_msg=kwargs["tag_forbidden_msg"],
        tag_exists_alert=kwargs["tag_exists_alert"],
        confirm_delete_label=kwargs["confirm_delete_label"],
        inline_keyboard_button=kwargs["inline_keyboard_button"],
        inline_keyboard_markup=kwargs["inline_keyboard_markup"],
        get_short_callback_data=kwargs["get_short_callback_data"],
        latency_tester=kwargs["latency_tester"],
        usage_audit_service=kwargs["usage_audit_service"],
        export_cache_service=kwargs["export_cache_service"],
        logger=kwargs["logger"],
        subscription_check_service=kwargs.get("subscription_check_service"),
        alert_preference_service=kwargs.get("alert_preference_service"),
    )


def _build_audit_handler(kwargs):
    return make_audit_callback_handler(
        is_owner=kwargs["is_owner"],
        admin_service=kwargs["admin_service"],
        access_service=kwargs.get("access_service"),
        post_init=kwargs.get("post_init"),
        user_manager=kwargs.get("user_manager"),
        get_storage=kwargs["get_storage"],
        backup_service=kwargs.get("backup_service"),
        logger=kwargs["logger"],
        build_usage_audit_keyboard=kwargs["build_usage_audit_keyboard"],
        build_recent_activity_keyboard=kwargs["build_recent_activity_keyboard"],
        build_owner_panel_keyboard=kwargs["build_owner_panel_keyboard"],
        inline_keyboard_button=kwargs["inline_keyboard_button"],
        inline_keyboard_markup=kwargs["inline_keyboard_markup"],
    )


async def _handle_callback(
    update,
    context,
    action: str,
    hash_key: str,
    deps: SubscriptionCallbackDeps,
    kwargs,
    audit_callback_handler,
    cache_callback_handler,
) -> bool:
    query = update.callback_query
    store = kwargs["get_storage"]()
    operator_uid = update.effective_user.id
    owner_mode = kwargs["is_owner"](update)
    if await audit_callback_handler(update, context, action, hash_key):
        return True
    if action in {"tag_apply", "tag_new"}:
        return await _handle_cached_tag_action(
            query, context, action, hash_key, store, operator_uid, owner_mode, deps
        )
    url = resolve_url(deps, hash_key, operator_uid=operator_uid)
    if await cache_callback_handler(update, context, action, url):
        return True
    if action in URL_REQUIRED_ACTIONS and not url:
        await query.answer("操作已过期，请重新发送链接后再试。", show_alert=True)
        return True
    return await _dispatch_url_action(
        update, context, action, hash_key, url, store, operator_uid, owner_mode, deps
    )


async def _handle_cached_tag_action(
    query, context, action, hash_key, store, operator_uid, owner_mode, deps
) -> bool:
    handler = handle_tag_apply if action == "tag_apply" else handle_tag_new
    return await handler(
        query,
        context,
        store=store,
        operator_uid=operator_uid,
        owner_mode=owner_mode,
        hash_key=hash_key,
        deps=deps,
    )


async def _dispatch_url_action(
    update, context, action, hash_key, url, store, operator_uid, owner_mode, deps
) -> bool:
    handler = _url_action_handlers(
        update, context, hash_key, url, store, operator_uid, owner_mode, deps
    ).get(action)
    if handler is None:
        return False
    await handler()
    return True


def _url_action_handlers(
    update, context, hash_key, url, store, operator_uid, owner_mode, deps
) -> dict:
    handlers = _simple_url_action_handlers(update, context, url, operator_uid, owner_mode, deps)
    handlers.update(
        _mutation_url_action_handlers(
            update, context, hash_key, url, store, operator_uid, owner_mode, deps
        )
    )
    return handlers


def _simple_url_action_handlers(update, context, url, operator_uid, owner_mode, deps) -> dict:
    query = update.callback_query
    return {
        "mute_alerts": lambda: handle_mute_alerts(
            query, context, operator_uid=operator_uid, deps=deps
        ),
        "unmute_alerts": lambda: handle_unmute_alerts(
            query, context, operator_uid=operator_uid, deps=deps
        ),
        "more_ops": lambda: handle_more_ops(
            query, context, url=url, owner_mode=owner_mode, operator_uid=operator_uid, deps=deps
        ),
        "basic_ops": lambda: handle_basic_ops(
            query, context, url=url, owner_mode=owner_mode, operator_uid=operator_uid, deps=deps
        ),
        "del_cancel": lambda: handle_delete_cancel(query, context),
    }


def _mutation_url_action_handlers(
    update, context, hash_key, url, store, operator_uid, owner_mode, deps
) -> dict:
    query = update.callback_query
    return {
        "recheck": lambda: handle_recheck(
            update,
            query,
            context,
            store=store,
            url=url,
            owner_mode=owner_mode,
            operator_uid=operator_uid,
            deps=deps,
        ),
        "delete": lambda: handle_delete_prompt(
            query,
            context,
            store=store,
            url=url,
            operator_uid=operator_uid,
            owner_mode=owner_mode,
            deps=deps,
        ),
        "del_confirm": lambda: handle_delete_confirm(
            query, context, store=store, url=url, operator_uid=operator_uid, owner_mode=owner_mode
        ),
        "ping": lambda: handle_ping(
            query,
            context,
            store=store,
            url=url,
            operator_uid=operator_uid,
            owner_mode=owner_mode,
            deps=deps,
        ),
        "tag": lambda: handle_tag_select(
            query,
            context,
            store=store,
            url=url,
            operator_uid=operator_uid,
            owner_mode=owner_mode,
            hash_key=hash_key,
            deps=deps,
        ),
    }
