"""
节点IP提取器
从各种协议的节点配置中提取真实IP地址
"""

import re
import base64
import json
import logging
from typing import Optional
from urllib.parse import urlparse, unquote

logger = logging.getLogger(__name__)


class NodeIPExtractor:
    """节点IP提取器"""
    
    @staticmethod
    def extract_ip(node: dict) -> Optional[str]:
        """
        从节点配置提取IP地址
        
        Args:
            node: 节点信息字典
            
        Returns:
            str: IP地址或域名
        """
        protocol = node.get('protocol', '').lower()
        raw = node.get('raw', '')
        
        # Clash YAML格式
        if 'server' in node:
            return node['server']
        
        # VMess协议
        if protocol == 'vmess':
            return NodeIPExtractor._extract_vmess_ip(raw)
        
        # VLess/Trojan协议
        elif protocol in ['vless', 'trojan']:
            return NodeIPExtractor._extract_url_based_ip(raw)
        
        # Shadowsocks协议
        elif protocol == 'ss':
            return NodeIPExtractor._extract_ss_ip(raw)
        
        # SSR协议
        elif protocol == 'ssr':
            return NodeIPExtractor._extract_ssr_ip(raw)
        
        # Hysteria协议
        elif protocol in ['hysteria', 'hysteria2']:
            return NodeIPExtractor._extract_url_based_ip(raw)
        
        return None
    
    @staticmethod
    def _extract_vmess_ip(raw: str) -> Optional[str]:
        """提取VMess协议的IP"""
        try:
            encoded = raw.replace('vmess://', '').strip()
            decoded = base64.b64decode(encoded).decode('utf-8')
            config = json.loads(decoded)
            return config.get('add')
        except Exception as e:
            logger.debug(f"VMess IP提取失败: {e}")
            return None
    
    @staticmethod
    def _extract_url_based_ip(raw: str) -> Optional[str]:
        """提取基于URL格式的协议IP (VLess/Trojan/Hysteria)"""
        try:
            # 格式: protocol://uuid@server:port?params#name
            match = re.search(r'@([^:/?#]+)', raw)
            if match:
                return match.group(1)
        except Exception as e:
            logger.debug(f"URL格式IP提取失败: {e}")
        return None
    
    @staticmethod
    def _extract_ss_ip(raw: str) -> Optional[str]:
        """提取Shadowsocks协议的IP"""
        try:
            # 格式: ss://base64(method:password)@server:port
            if '@' in raw:
                server_part = raw.split('@')[1].split('#')[0]
                server = server_part.split(':')[0]
                return server
            else:
                # 全Base64编码格式
                encoded = raw.replace('ss://', '').split('#')[0]
                decoded = base64.b64decode(encoded).decode('utf-8')
                match = re.search(r'@([^:]+):', decoded)
                if match:
                    return match.group(1)
        except Exception as e:
            logger.debug(f"SS IP提取失败: {e}")
        return None
    
    @staticmethod
    def _extract_ssr_ip(raw: str) -> Optional[str]:
        """提取SSR协议的IP"""
        try:
            encoded = raw.replace('ssr://', '').strip()
            decoded = base64.b64decode(encoded).decode('utf-8')
            # 格式: server:port:protocol:method:obfs:password_base64
            parts = decoded.split(':')
            if len(parts) >= 6:
                return parts[0]
        except Exception as e:
            logger.debug(f"SSR IP提取失败: {e}")
        return None
    
    @staticmethod
    def is_valid_ip(ip: str) -> bool:
        """验证是否为有效的IP地址"""
        if not ip:
            return False
        
        # IPv4验证
        ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if re.match(ipv4_pattern, ip):
            parts = ip.split('.')
            return all(0 <= int(part) <= 255 for part in parts)
        
        # 域名验证(简单检查)
        domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
        return bool(re.match(domain_pattern, ip))
