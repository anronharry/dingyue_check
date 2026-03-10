"""
单元测试 - 工具函数模块
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.utils import (
    bytes_to_gb,
    format_traffic,
    is_valid_url,
    create_progress_bar,
    get_country_flag,
    format_remaining_time
)


class TestTrafficFormatting:
    """流量格式化测试"""
    
    def test_bytes_to_gb(self):
        """测试字节转 GB"""
        assert bytes_to_gb(1024**3) == 1.0
        assert bytes_to_gb(2 * 1024**3) == 2.0
        assert bytes_to_gb(0) == 0
        assert bytes_to_gb(None) == 0
    
    def test_format_traffic(self):
        """测试流量格式化"""
        assert format_traffic(0) == "0 B"
        assert format_traffic(1024) == "1.00 KB"
        assert format_traffic(1024**2) == "1.00 MB"
        assert format_traffic(1024**3) == "1.00 GB"
        assert format_traffic(1.5 * 1024**3) == "1.50 GB"
        assert format_traffic(None) == "0 B"


class TestURLValidation:
    """URL 验证测试"""
    
    def test_valid_urls(self):
        """测试有效 URL"""
        assert is_valid_url("https://example.com")
        assert is_valid_url("http://example.com/api/v1/subscribe")
        assert is_valid_url("https://sub.example.com:8080/path?token=abc123")
    
    def test_invalid_urls(self):
        """测试无效 URL"""
        assert not is_valid_url("")
        assert not is_valid_url("not a url")
        assert not is_valid_url("example.com")  # 缺少 scheme
        assert not is_valid_url("ftp://example.com")  # scheme 存在但可能不被接受


class TestProgressBar:
    """进度条测试"""
    
    def test_progress_bar_boundaries(self):
        """测试进度条边界情况"""
        assert create_progress_bar(0) == "[□□□□□□□□□□]"
        assert create_progress_bar(100) == "[■■■■■■■■■■]"
        assert create_progress_bar(50) == "[■■■■■□□□□□]"
    
    def test_progress_bar_overflow(self):
        """测试进度条溢出处理"""
        assert create_progress_bar(-10) == "[□□□□□□□□□□]"
        assert create_progress_bar(150) == "[■■■■■■■■■■]"
    
    def test_progress_bar_small_values(self):
        """测试小百分比值"""
        result = create_progress_bar(1)
        assert result.count("■") >= 1  # 至少显示一个


class TestCountryFlag:
    """国家国旗测试"""
    
    def test_known_countries(self):
        """测试已知国家"""
        assert get_country_flag("香港") == "🇭🇰"
        assert get_country_flag("美国") == "🇺🇸"
        assert get_country_flag("日本") == "🇯🇵"
        assert get_country_flag("其他") == "🌐"
    
    def test_unknown_country(self):
        """测试未知国家"""
        assert get_country_flag("火星") == "🏳️"


class TestRemainingTime:
    """剩余时间格式化测试"""
    
    def test_expired_time(self):
        """测试已过期时间"""
        result = format_remaining_time("2020-01-01 00:00:00")
        assert result == "已过期"
    
    def test_future_time(self):
        """测试未来时间"""
        result = format_remaining_time("2099-12-31 23:59:59")
        assert "天" in result
    
    def test_invalid_format(self):
        """测试无效格式"""
        result = format_remaining_time("invalid date")
        assert result == ""


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
