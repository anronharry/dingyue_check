"""Tag-related subscription callback actions."""

from __future__ import annotations

import html
from typing import Any

from handlers.callbacks.subscription_utils import SubscriptionCallbackDeps, build_callback


async def handle_tag_apply(
    query: Any,
    context: Any,
    *,
    store: Any,
    operator_uid: int,
    owner_mode: bool,
    hash_key: str,
    deps: SubscriptionCallbackDeps,
) -> bool:
    del context
    await query.answer("正在处理标签...")
    url, tag = _resolve_tag_apply_target(query, operator_uid, hash_key, deps)
    if not url:
        return True

    if store.add_tag(url, tag, operator_uid=operator_uid, require_owner=not owner_mode):
        await query.edit_message_text(
            f"已添加标签：{tag}\n订阅：{store.get_all().get(url, {}).get('name', url)}"
        )
        return True
    await _reply_tag_apply_failure(query, store, url, tag, operator_uid, owner_mode, deps)
    return True


def _resolve_tag_apply_target(
    query: Any, operator_uid: int, hash_key: str, deps: SubscriptionCallbackDeps
) -> tuple[str | None, str]:
    parts = hash_key.split("|", 1)
    if len(parts) != 2:
        return None, ""
    url_hash, tag = parts
    deps.cleanup_url_cache()
    cache_entry = deps.url_cache.get(url_hash)
    if _cache_belongs_to_other_user(cache_entry, operator_uid):
        return None, tag
    url = cache_entry.get("url") if cache_entry else None
    return url, tag


async def _reply_tag_apply_failure(
    query: Any,
    store: Any,
    url: str,
    tag: str,
    operator_uid: int,
    owner_mode: bool,
    deps: SubscriptionCallbackDeps,
) -> None:
    sub = store.get_all().get(url, {})
    sub_owner = sub.get("owner_uid", 0)
    if sub_owner and sub_owner != operator_uid and not owner_mode:
        await query.answer("无权修改他人的订阅标签", show_alert=True)
        await query.edit_message_text(deps.tag_forbidden_msg)
        return
    await query.answer(deps.tag_exists_alert, show_alert=True)
    await query.edit_message_text(f"标签“{tag}”已存在，无需重复添加")


async def handle_tag_new(
    query: Any,
    context: Any,
    *,
    store: Any,
    operator_uid: int,
    owner_mode: bool,
    hash_key: str,
    deps: SubscriptionCallbackDeps,
) -> bool:
    await query.answer("准备新建标签...")
    url = await _resolve_cached_url_or_alert(query, hash_key, operator_uid, deps)
    if not url:
        return True
    sub = store.get_all().get(url, {})
    if sub.get("owner_uid", 0) not in {0, operator_uid} and not owner_mode:
        await query.answer("无权修改他人的订阅标签", show_alert=True)
        return True
    await query.edit_message_text(f"请发送新标签名称：\n订阅：{sub.get('name', url)}")
    context.user_data["pending_tag_url"] = url
    return True


async def handle_tag_select(
    query: Any,
    context: Any,
    *,
    store: Any,
    url: str,
    operator_uid: int,
    owner_mode: bool,
    hash_key: str,
    deps: SubscriptionCallbackDeps,
) -> bool:
    await query.answer("正在加载标签选项...")
    sub = store.get_all().get(url, {})
    sub_owner = sub.get("owner_uid", 0)
    if sub_owner and sub_owner != operator_uid and not owner_mode:
        await query.answer("无权修改他人的订阅标签", show_alert=True)
        return True
    existing_tags = sorted(
        {tag for data in store.get_by_user(operator_uid).values() for tag in data.get("tags", [])}
    )
    if existing_tags:
        await _reply_existing_tags(
            query, sub.get("name", url), existing_tags, hash_key, url, operator_uid, deps
        )
        return True
    await query.edit_message_text(f"请发送标签名称：\n订阅：{sub.get('name', url)}")
    context.user_data["pending_tag_url"] = url
    return True


async def _reply_existing_tags(
    query: Any,
    sub_name: str,
    existing_tags: list[str],
    hash_key: str,
    url: str,
    operator_uid: int,
    deps: SubscriptionCallbackDeps,
) -> None:
    tag_buttons = _build_tag_buttons(existing_tags, hash_key, url, operator_uid, deps)
    await query.edit_message_text(
        f"为 <b>{html.escape(sub_name)}</b> 选择或新建标签：",
        parse_mode="HTML",
        reply_markup=deps.inline_keyboard_markup(tag_buttons),
    )


def _build_tag_buttons(
    existing_tags: list[str],
    hash_key: str,
    url: str,
    operator_uid: int,
    deps: SubscriptionCallbackDeps,
) -> list[list[Any]]:
    tag_buttons: list[list[Any]] = []
    row: list[Any] = []
    for tag in existing_tags:
        callback = f"tag_apply:{hash_key}|{tag}"
        if len(callback) <= 64:
            row.append(deps.inline_keyboard_button(f"标签 {tag}", callback_data=callback))
        if len(row) == 2:
            tag_buttons.append(row)
            row = []
    if row:
        tag_buttons.append(row)
    tag_buttons.append(
        [
            deps.inline_keyboard_button(
                "新建标签", callback_data=build_callback(deps, "tag_new", url, operator_uid)
            )
        ]
    )
    return tag_buttons


async def _resolve_cached_url_or_alert(
    query: Any, hash_key: str, operator_uid: int, deps: SubscriptionCallbackDeps
) -> str | None:
    deps.cleanup_url_cache()
    cache_entry = deps.url_cache.get(hash_key)
    if _cache_belongs_to_other_user(cache_entry, operator_uid):
        await query.answer("操作已过期，请重新发起。", show_alert=True)
        return None
    url = cache_entry.get("url") if cache_entry else None
    if not url:
        await query.answer("操作已过期，请重新发起。", show_alert=True)
        return None
    return url


def _cache_belongs_to_other_user(cache_entry: Any, operator_uid: int) -> bool:
    cache_uid = int(cache_entry.get("uid", 0) or 0) if cache_entry else 0
    return bool(cache_uid and cache_uid != operator_uid)
