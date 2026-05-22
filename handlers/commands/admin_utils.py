"""Shared admin command utility functions."""

from __future__ import annotations

import asyncio
import html
import os
from typing import Any


async def deliver_broadcast(
    *, bot: Any, user_ids: Any, content: str, logger: Any, title: str = "系统广播（管理员）"
) -> tuple[int, int]:
    """Send broadcast and return (success, failed)."""
    message_text = f"<b>{html.escape(title)}</b>\n\n{html.escape(content)}"
    success, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=message_text, parse_mode="HTML")
            success += 1
        except Exception as exc:
            failed += 1
            if logger:
                logger.warning("Broadcast send failed uid=%s error=%s", uid, exc)
    return success, failed


async def export_subscriptions_file(
    *, store: Any, admin_service: Any
) -> tuple[bool, str, str, int]:
    """Export subscriptions to file and return (ok, file_path, file_name, total)."""
    export_file, export_name = admin_service.make_export_file_path()
    ok = await asyncio.get_event_loop().run_in_executor(None, store.export_to_file, export_file)
    return ok, export_file, export_name, len(store.get_all())


async def create_backup_file(*, backup_service: Any) -> tuple[str, str]:
    """Create backup zip and return (zip_path, zip_name)."""
    return await asyncio.get_event_loop().run_in_executor(None, backup_service.create_backup)


async def remove_file_async(file_path: str) -> None:
    await asyncio.get_event_loop().run_in_executor(None, os.remove, file_path)
