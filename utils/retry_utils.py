"""
重试机制工具模块
提供网络请求重试装饰器，支持指数退避
"""
from __future__ import annotations


import time
import asyncio
import random
import logging
from functools import wraps
from typing import Callable, TypeVar, Any, Optional
import aiohttp

def async_retry_on_failure(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (aiohttp.ClientError, asyncio.TimeoutError)
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    异步网络请求重试装饰器（指数退避 + 随机抖动）

    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟时间（秒）
        backoff_factor: 退避因子
        exceptions: 需要重试的异常类型
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries):
                try:
                    result = await func(*args, **kwargs)
                    if attempt > 0:
                        logger.info(f"✅ {func.__name__} 重试成功 (第 {attempt + 1} 次尝试)")
                    return result

                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries - 1:
                        logger.error(f"❌ {func.__name__} 异步重试失败 (已重试 {max_retries} 次): {e}")
                        raise

                    logger.warning(f"⚠️ {func.__name__} 异步失败，{delay:.1f}s 后重试 ({attempt + 1}/{max_retries}): {e}")
                    jitter = delay * 0.25 * random.random()
                    await asyncio.sleep(delay + jitter)
                    delay *= backoff_factor

            if last_exception:
                raise last_exception
            raise RuntimeError("异步重试逻辑异常")

        return wrapper
    return decorator
