"""
文件处理器
处理TXT/YAML文件的解析和转换
"""

import base64
import yaml
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class FileHandler:
    """文件处理器"""
    
    @staticmethod
    def extract_subscription_urls(content: bytes) -> List[str]:
        """
        从文件内容中提取订阅链接
        
        Args:
            content: 文件内容(字节)
            
        Returns:
            list: 订阅链接列表
        """
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            text = content.decode('gbk', errors='ignore')
        
        # 提取所有http/https链接
        import re
        urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', text)
        
        # 过滤出可能的订阅链接
        subscription_urls = []
        for url in urls:
            # 排除明显不是订阅的链接
            if any(ext in url.lower() for ext in ['.jpg', '.png', '.gif', '.mp4', '.pdf']):
                continue
            subscription_urls.append(url)
        
        return subscription_urls
    
    @staticmethod
    def parse_txt_file(content: bytes) -> List[Dict]:
        """
        解析TXT文件
        
        Args:
            content: 文件内容(字节)
            
        Returns:
            list: 节点列表
        """
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            text = content.decode('gbk', errors='ignore')
        
        # 尝试Base64解码
        if FileHandler._is_base64(text):
            try:
                decoded = base64.b64decode(text).decode('utf-8')
                text = decoded
            except:
                pass
        
        # 解析节点
        nodes = []
        protocols = ['vmess://', 'vless://', 'ss://', 'ssr://', 'trojan://', 'hysteria://', 'hysteria2://']
        
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            for protocol in protocols:
                if line.startswith(protocol):
                    nodes.append({
                        'protocol': protocol.replace('://', ''),
                        'raw': line,
                        'name': FileHandler._extract_node_name(line)
                    })
                    break
        
        return nodes
    
    @staticmethod
    def parse_yaml_file(content: bytes) -> List[Dict]:
        """
        解析YAML文件
        
        Args:
            content: 文件内容(字节)
            
        Returns:
            list: 节点列表
        """
        try:
            text = content.decode('utf-8')
            config = yaml.safe_load(text)
            
            nodes = []
            if config and 'proxies' in config:
                for proxy in config['proxies']:
                    if isinstance(proxy, dict):
                        nodes.append({
                            'name': proxy.get('name', '未知节点'),
                            'protocol': proxy.get('type', 'unknown').lower(),
                            'server': proxy.get('server', ''),
                            'port': proxy.get('port', 0)
                        })
            
            return nodes
            
        except Exception as e:
            logger.error(f"YAML解析失败: {e}")
            return []
    
    @staticmethod
    def convert_to_yaml(nodes: List[Dict]) -> str:
        """
        将节点列表转换为Clash YAML格式
        
        Args:
            nodes: 节点列表
            
        Returns:
            str: YAML配置文本
        """
        config = {
            'proxies': []
        }
        
        for node in nodes:
            # 这里只生成基本结构,实际需要根据协议解析详细配置
            proxy = {
                'name': node.get('name', '未知节点'),
                'type': node.get('protocol', 'ss'),
                'server': node.get('server', 'unknown'),
                'port': node.get('port', 0)
            }
            config['proxies'].append(proxy)
        
        return yaml.dump(config, allow_unicode=True, default_flow_style=False)
    
    @staticmethod
    def _is_base64(text: str) -> bool:
        """判断文本是否为Base64编码"""
        text = text.strip()
        if not text:
            return False
        
        # Base64字符集检查
        base64_pattern = r'^[A-Za-z0-9+/]*={0,2}$'
        if not text.replace('\n', '').replace('\r', ''):
            return False
        
        # 长度检查(Base64长度必须是4的倍数)
        clean_text = text.replace('\n', '').replace('\r', '')
        return len(clean_text) % 4 == 0 and bool(re.match(base64_pattern, clean_text))
    
    @staticmethod
    def _extract_node_name(line: str) -> str:
        """从节点配置提取名称"""
        if '#' in line:
            name = line.split('#', 1)[1]
            try:
                from urllib.parse import unquote
                name = unquote(name)
            except:
                pass
            return name.strip()
        
        return "未命名节点"


# 导入re模块
import re
