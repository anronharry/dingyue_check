"""Web admin server package."""

from __future__ import annotations

from typing import Any

__all__ = ["build_web_app"]


def __getattr__(name: str) -> Any:
    if name == "build_web_app":
        from .app_factory import build_web_app

        return build_web_app
    raise AttributeError(name)
