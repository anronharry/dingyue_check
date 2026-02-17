"""
智能输入类型检测器
自动识别用户输入的类型(URL/文件/节点文本)
"""

import re
from typing import Literal


class InputDetector:
    """智能输入检测器"""
    
    @staticmethod
    def detect_message_type(update) -> Literal['file', 'url', 'node_text', 'unknown']:
        """
        检测消息类型
        
        Args:
            update: Telegram Update对象
            
        Returns:
            str: 'file', 'url', 'node_text', 'unknown'
        """
        # 检测文件
        if update.message.document:
            return 'file'
        
        # 检测文本
        if update.message.text:
            text = update.message.text.strip()
            
            # 检测URL
            if InputDetector.is_subscription_url(text):
                return 'url'
            
            # 检测节点文本
            if InputDetector.is_node_text(text):
                return 'node_text'
        
        return 'unknown'
    
    @staticmethod
    def is_subscription_url(text: str) -> bool:
        """判断是否为订阅链接"""
        # 检查是否包含http/https
        if not text.startswith(('http://', 'https://')):
            return False
        
        # 简单的URL格式验证
        url_pattern = r'^https?://[^\s]+$'
        lines = text.split('\n')
        
        # 支持多行URL
        return all(re.match(url_pattern, line.strip()) for line in lines if line.strip())
    
    @staticmethod
    def is_node_text(text: str) -> bool:
        """判断是否为节点文本列表"""
        protocols = ['vmess://', 'vless://', 'ss://', 'ssr://', 'trojan://', 'hysteria://', 'hysteria2://']
        
        lines = text.split('\n')
        valid_lines = [line.strip() for line in lines if line.strip()]
        
        if not valid_lines:
            return False
        
        # 至少50%的行是有效节点
        node_count = sum(1 for line in valid_lines if any(line.startswith(p) for p in protocols))
        return node_count >= len(valid_lines) * 0.5
    
    @staticmethod
    def detect_file_type(filename: str) -> Literal['txt', 'yaml', 'json', 'unknown']:
        """
        检测文件类型
        
        Args:
            filename: 文件名
            
        Returns:
            str: 'txt', 'yaml', 'json', 'unknown'
        """
        filename_lower = filename.lower()
        
        if filename_lower.endswith('.txt'):
            return 'txt'
        elif filename_lower.endswith(('.yaml', '.yml')):
            return 'yaml'
        elif filename_lower.endswith('.json'):
            return 'json'
        
        return 'unknown'
