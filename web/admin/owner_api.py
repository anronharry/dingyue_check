"""Owner-only Web Admin API handlers."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from web.admin.users_api import _json_error, _json_exception
from web.constants import RUNTIME_KEY

IMPORT_JSON_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_RESTORE_MAX_BYTES = 200 * 1024 * 1024
OWNER_CHECK_CONCURRENCY = 20

logger = logging.getLogger(__name__)


async def _read_upload(
    request: web.Request, *, suffix: str, default_name: str
) -> tuple[str, bytes, web.Response | None]:
    try:
        form = await request.post()
    except Exception:
        return "", b"", _json_error("invalid_form", status=400)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "file"):
        return "", b"", _json_error("file_required", status=400)
    filename = str(getattr(upload, "filename", "") or default_name)
    if not filename.lower().endswith(suffix):
        return "", b"", _json_error("invalid_file_type", status=400)
    content = await asyncio.to_thread(upload.file.read)
    if not isinstance(content, (bytes, bytearray)) or not content:
        return "", b"", _json_error("empty_file", status=400)
    return filename, bytes(content), None


async def _owner_export_json(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    export_file = ""
    export_name = "subscriptions_export.json"
    try:
        store = runtime.get_storage()
        export_file, export_name = await asyncio.to_thread(
            runtime.admin_service.make_export_file_path
        )
        ok = await asyncio.to_thread(store.export_to_file, export_file)
        if not ok:
            return _json_error("export_failed", status=500)
        payload = await asyncio.to_thread(Path(export_file).read_bytes)
        return web.Response(
            body=payload,
            content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{export_name}"'},
        )
    except Exception as exc:
        return _json_exception("export_failed", exc)
    finally:
        await _delete_export_file(export_file)


async def _delete_export_file(export_file: str) -> None:
    if not export_file:
        return
    path = Path(export_file)
    try:
        if path.exists():
            await asyncio.to_thread(path.unlink)
    except Exception as exc:
        logger.warning("failed to delete temporary export file %s: %s", export_file, exc)


async def _owner_import_json(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    filename, content, err = await _read_upload(request, suffix=".json", default_name="import.json")
    if err is not None:
        return err
    if len(content) > IMPORT_JSON_MAX_BYTES:
        return _json_error("file_too_large", status=400)
    try:
        imported = await runtime.document_service.import_json(content_bytes=content)
        return web.json_response(
            {"ok": True, "data": {"imported": int(imported), "filename": filename}}
        )
    except Exception as exc:
        return _json_exception("import_failed", exc)


async def _owner_backup_download(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    try:
        zip_path, zip_name = await asyncio.to_thread(runtime.backup_service.create_backup)
        payload = await asyncio.to_thread(Path(zip_path).read_bytes)
        return web.Response(
            body=payload,
            content_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
        )
    except Exception as exc:
        return _json_exception("backup_failed", exc)


async def _owner_restore_backup(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    filename, content, err = await _read_upload(request, suffix=".zip", default_name="backup.zip")
    if err is not None:
        return err
    max_bytes = int(
        getattr(runtime.backup_service, "max_restore_total_bytes", DEFAULT_RESTORE_MAX_BYTES)
    )
    if len(content) > max_bytes:
        return _json_error("file_too_large", status=400)
    try:
        restored = await asyncio.to_thread(runtime.backup_service.restore_backup_bytes, content)
        data = {"restored_files": len(restored), "preview": restored[:20], "filename": filename}
        return web.json_response({"ok": True, "data": data})
    except Exception as exc:
        return _json_exception("restore_failed", exc)


async def _check_subscription(runtime: Any, store: Any, url: str, data: dict[str, Any]) -> bool:
    owner_uid = int(data.get("owner_uid", 0) or 0)
    try:
        if runtime.subscription_check_service:
            await runtime.subscription_check_service.parse_and_store(url=url, owner_uid=owner_uid)
        else:
            parser_instance = await runtime.get_parser()
            result = await parser_instance.parse(url)
            await asyncio.to_thread(store.add_or_update, url, result, owner_uid)
        return True
    except Exception as exc:
        await _mark_check_failed(store, url, exc)
        return False


async def _mark_check_failed(store: Any, url: str, exc: Exception) -> None:
    try:
        await asyncio.to_thread(store.mark_check_failed, url, str(exc))
    except Exception as mark_exc:
        logger.warning("failed to mark subscription check failure for %s: %s", url, mark_exc)


async def _owner_check_all(request: web.Request) -> web.Response:
    runtime = request.app[RUNTIME_KEY]
    store = runtime.get_storage()
    subscriptions = await asyncio.to_thread(store.get_all)
    if not subscriptions:
        return web.json_response({"ok": True, "data": {"total": 0, "success": 0, "failed": 0}})
    semaphore = asyncio.Semaphore(OWNER_CHECK_CONCURRENCY)

    async def check_one(url: str, data: dict[str, Any]) -> bool:
        async with semaphore:
            return await _check_subscription(runtime, store, url, data)

    await asyncio.to_thread(store.begin_batch)
    try:
        results = await asyncio.gather(
            *[check_one(url, data) for url, data in subscriptions.items()]
        )
    finally:
        await asyncio.to_thread(store.end_batch, True)
    success = sum(1 for row in results if row)
    failed = len(results) - success
    return web.json_response(
        {"ok": True, "data": {"total": len(results), "success": success, "failed": failed}}
    )
