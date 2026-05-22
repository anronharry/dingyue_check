"""Static Web Admin page handlers."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web


def _get_admin_static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


async def _login_page(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(_get_admin_static_dir() / "login.html")


async def _admin_index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(_get_admin_static_dir() / "index.html")


async def _aggregate_page(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(_get_admin_static_dir() / "aggregate.html")
