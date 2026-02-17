"""
IP地理位置查询服务
使用 ip-api.com 免费API查询IP地理位置
"""

import requests
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class GeoLocationService:
    """IP地理位置查询服务"""
    
    def __init__(self):
        self.cache: Dict[str, Dict] = {}
        self.api_url = "http://ip-api.com/json/{}"
    
    def get_location(self, ip: str) -> Optional[Dict]:
        """
        查询IP地理位置
        
        Args:
            ip: IP地址
            
        Returns:
            dict: 地理位置信息 {'country', 'city', 'isp', 'country_code'}
        """
        if not ip or ip == 'unknown':
            return None
        
        # 检查缓存
        if ip in self.cache:
            return self.cache[ip]
        
        try:
            response = requests.get(
                self.api_url.format(ip),
                timeout=5
            )
            data = response.json()
            
            if data.get('status') == 'success':
                location = {
                    'country': data.get('country', '未知'),
                    'city': data.get('city', '未知'),
                    'isp': data.get('isp', '未知'),
                    'country_code': data.get('countryCode', '')
                }
                self.cache[ip] = location
                return location
            else:
                logger.warning(f"IP查询失败: {ip} - {data.get('message')}")
                return None
                
        except Exception as e:
            logger.error(f"查询IP地理位置失败 {ip}: {e}")
            return None
    
    def get_country_flag(self, country_code: str) -> str:
        """
        根据国家代码返回国旗emoji
        
        Args:
            country_code: 国家代码(如 HK, US)
            
        Returns:
            str: 国旗emoji
        """
        if not country_code or len(country_code) != 2:
            return '🌐'
        
        # 将国家代码转换为区域指示符号(Regional Indicator Symbols)
        # A-Z的Unicode范围是U+1F1E6到U+1F1FF
        code_points = [ord(c) + 127397 for c in country_code.upper()]
        return ''.join(chr(c) for c in code_points)
