"""
重试机制工具模块
提供网络请求重试装饰器，支持指数退避和详细日志
"""

import time
import logging
from functools import wraps
from typing import Callable, TypeVar, Any, Optional
import requests

logger = logging.getLogger(__name__)

T = TypeVar('T')


def retry_on_failure(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (requests.RequestException, ConnectionError, TimeoutError)
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    网络请求重试装饰器（指数退避策略）
    
    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟时间（秒）
        backoff_factor: 退避因子（每次重试延迟时间的倍数）
        exceptions: 需要重试的异常类型元组
        
    Returns:
        装饰后的函数
        
    示例:
        @retry_on_failure(max_retries=3, initial_delay=1.0)
        def fetch_data(url):
            return requests.get(url)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            delay = initial_delay
            last_exception: Optional[Exception] = None
            
            for attempt in range(max_retries):
                try:
                    result = func(*args, **kwargs)
                    
                    # 如果不是第一次尝试，记录成功日志
                    if attempt > 0:
                        logger.info(
                            f"✅ {func.__name__} 重试成功 "
                            f"(第 {attempt + 1} 次尝试)"
                        )
                    
                    return result
                    
                except exceptions as e:
                    last_exception = e
                    
                    # 如果是最后一次尝试，不再重试
                    if attempt == max_retries - 1:
                        logger.error(
                            f"❌ {func.__name__} 失败 "
                            f"(已重试 {max_retries} 次): {str(e)}"
                        )
                        raise
                    
                    # 记录重试日志
                    logger.warning(
                        f"⚠️ {func.__name__} 失败，{delay:.1f}秒后重试 "
                        f"(第 {attempt + 1}/{max_retries} 次): {str(e)}"
                    )
                    
                    # 等待后重试
                    time.sleep(delay)
                    delay *= backoff_factor  # 指数退避
                    
            # 理论上不会到这里，但为了类型安全
            if last_exception:
                raise last_exception
            raise RuntimeError("重试逻辑异常")
            
        return wrapper
    return decorator


class RetrySession:
    """
    带重试功能的 requests.Session 包装器
    适用于需要复用连接的场景，节省内存
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
        timeout: int = 30
    ):
        """
        初始化重试会话
        
        Args:
            max_retries: 最大重试次数
            initial_delay: 初始延迟时间（秒）
            backoff_factor: 退避因子
            timeout: 请求超时时间（秒）
        """
        self.session = requests.Session()
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.timeout = timeout
        
    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """
        发送 GET 请求（带重试）
        
        Args:
            url: 请求 URL
            **kwargs: 传递给 requests.get 的其他参数
            
        Returns:
            Response 对象
        """
        @retry_on_failure(
            max_retries=self.max_retries,
            initial_delay=self.initial_delay,
            backoff_factor=self.backoff_factor
        )
        def _get():
            return self.session.get(
                url,
                timeout=kwargs.pop('timeout', self.timeout),
                **kwargs
            )
        
        return _get()
    
    def close(self):
        """关闭会话，释放资源"""
        self.session.close()
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口，自动关闭会话"""
        self.close()


def safe_request(
    url: str,
    method: str = 'GET',
    max_retries: int = 3,
    **kwargs: Any
) -> Optional[requests.Response]:
    """
    安全的 HTTP 请求函数（带重试和异常处理）
    
    Args:
        url: 请求 URL
        method: 请求方法（GET/POST）
        max_retries: 最大重试次数
        **kwargs: 传递给 requests 的其他参数
        
    Returns:
        Response 对象，失败返回 None
    """
    @retry_on_failure(max_retries=max_retries)
    def _request():
        if method.upper() == 'GET':
            return requests.get(url, **kwargs)
        elif method.upper() == 'POST':
            return requests.post(url, **kwargs)
        else:
            raise ValueError(f"不支持的请求方法: {method}")
    
    try:
        return _request()
    except Exception as e:
        logger.error(f"请求完全失败: {url}, 错误: {e}")
        return None
