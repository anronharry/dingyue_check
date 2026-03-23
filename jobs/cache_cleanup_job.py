"""Periodic cache cleanup job."""
from __future__ import annotations



async def run_cache_cleanup(context, cleanup_fn):
    cleanup_fn()
