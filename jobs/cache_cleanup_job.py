"""Periodic cache cleanup job."""


async def run_cache_cleanup(context, cleanup_fn):
    cleanup_fn()
