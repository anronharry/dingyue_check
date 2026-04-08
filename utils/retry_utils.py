"""
重试工具模块
提供异步网络请求重试装饰器，支持指数退避和随机抖动。
"""
from __future__ import annotations

import asyncio
import logging
import random
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

import aiohttp

logger = logging.getLogger(__name__)

T = TypeVar("T")


def async_retry_on_failure(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (aiohttp.ClientError, asyncio.TimeoutError),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    异步重试装饰器（指数退避 + 随机抖动）。

    Args:
        max_retries: 最大重试次数。
        initial_delay: 初始重试等待时间（秒）。
        backoff_factor: 每次重试后的退避倍率。
        exceptions: 触发重试的异常类型。
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = initial_delay
            last_exception: Optional[Exception] = None

            for attempt in range(1, max_retries + 1):
                try:
                    result = await func(*args, **kwargs)
                    if attempt > 1:
                        logger.info(
                            "%s 重试成功（第 %s/%s 次）。",
                            func.__name__,
                            attempt,
                            max_retries,
                        )
                    return result
                except exceptions as exc:
                    last_exception = exc
                    if attempt >= max_retries:
                        logger.error(
                            "%s 异步请求失败，已重试 %s 次，最后错误：%r",
                            func.__name__,
                            max_retries,
                            exc,
                        )
                        raise

                    logger.warning(
                        "%s 异步请求失败，将在 %.1f 秒后重试（第 %s/%s 次），错误：%r",
                        func.__name__,
                        delay,
                        attempt,
                        max_retries,
                        exc,
                    )
                    jitter = delay * 0.25 * random.random()
                    await asyncio.sleep(delay + jitter)
                    delay *= backoff_factor

            if last_exception:
                raise last_exception
            raise RuntimeError("异步重试逻辑异常：未记录到具体错误")

        return wrapper

    return decorator
