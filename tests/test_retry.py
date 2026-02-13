"""
单元测试 - 重试机制
"""

import pytest
import time
from unittest.mock import Mock, patch
import requests
from retry_utils import retry_on_failure, RetrySession, safe_request


class TestRetryDecorator:
    """重试装饰器测试"""
    
    def test_success_on_first_try(self):
        """测试第一次就成功"""
        call_count = 0
        
        @retry_on_failure(max_retries=3)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = successful_func()
        
        assert result == "success"
        assert call_count == 1
    
    def test_success_after_retries(self):
        """测试重试后成功"""
        call_count = 0
        
        @retry_on_failure(max_retries=3, initial_delay=0.1)
        def retry_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise requests.RequestException("Temporary error")
            return "success"
        
        result = retry_then_success()
        
        assert result == "success"
        assert call_count == 3
    
    def test_fail_after_max_retries(self):
        """测试达到最大重试次数后失败"""
        call_count = 0
        
        @retry_on_failure(max_retries=3, initial_delay=0.1)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise requests.RequestException("Permanent error")
        
        with pytest.raises(requests.RequestException):
            always_fail()
        
        assert call_count == 3
    
    def test_exponential_backoff(self):
        """测试指数退避"""
        call_times = []
        
        @retry_on_failure(max_retries=3, initial_delay=0.1, backoff_factor=2.0)
        def track_timing():
            call_times.append(time.time())
            if len(call_times) < 3:
                raise requests.RequestException("Error")
            return "success"
        
        track_timing()
        
        # 验证延迟时间递增
        assert len(call_times) == 3
        delay1 = call_times[1] - call_times[0]
        delay2 = call_times[2] - call_times[1]
        
        # 第二次延迟应该约为第一次的2倍
        assert delay2 > delay1


class TestRetrySession:
    """重试会话测试"""
    
    @patch('requests.Session.get')
    def test_session_get_success(self, mock_get):
        """测试会话 GET 请求成功"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        with RetrySession(max_retries=3) as session:
            response = session.get("https://example.com")
        
        assert response.status_code == 200
        assert mock_get.called
    
    @patch('requests.Session.get')
    def test_session_get_with_retry(self, mock_get):
        """测试会话 GET 请求重试"""
        # 前两次失败，第三次成功
        mock_get.side_effect = [
            requests.RequestException("Error 1"),
            requests.RequestException("Error 2"),
            Mock(status_code=200)
        ]
        
        with RetrySession(max_retries=3, initial_delay=0.1) as session:
            response = session.get("https://example.com")
        
        assert response.status_code == 200
        assert mock_get.call_count == 3


class TestSafeRequest:
    """安全请求函数测试"""
    
    @patch('requests.get')
    def test_safe_request_success(self, mock_get):
        """测试安全请求成功"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        response = safe_request("https://example.com", max_retries=3)
        
        assert response is not None
        assert response.status_code == 200
    
    @patch('requests.get')
    def test_safe_request_failure(self, mock_get):
        """测试安全请求失败返回 None"""
        mock_get.side_effect = requests.RequestException("Error")
        
        response = safe_request("https://example.com", max_retries=2)
        
        assert response is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
