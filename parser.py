"""
订阅链接解析模块
负责下载、解析和提取订阅信息
"""

import base64
import re
import requests
import yaml
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

# 禁用 SSL 警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SubscriptionParser:
    """订阅解析器"""
    
    def __init__(self, proxy_port=7890, use_proxy=False):
        """
        初始化解析器
        
        Args:
            proxy_port: 代理端口，默认 7890
            use_proxy: 是否使用代理，默认 False
        """
        self.proxy_port = proxy_port
        self.use_proxy = use_proxy
        
        if use_proxy:
            self.proxies = {
                'http': f'http://127.0.0.1:{proxy_port}',
                'https': f'http://127.0.0.1:{proxy_port}'
            }
        else:
            self.proxies = None
    
    def parse(self, url):
        """
        解析订阅链接
        
        Args:
            url: 订阅链接
            
        Returns:
            dict: 包含订阅信息的字典
        """
        try:
            # 下载订阅内容
            response = self._download_subscription(url)
            
            # 解析流量信息（从响应头）
            traffic_info = self._parse_traffic_info(response.headers)
            
            # 解析节点信息
            nodes = self._parse_nodes(response.text)
            
            # 提取机场名称（优先从响应头 Content-Disposition 提取）
            airport_name = self._extract_airport_name(nodes, url, response.headers)
            
            # 统计节点信息
            node_stats = self._analyze_nodes(nodes)
            
            # 组合结果
            result = {
                'name': airport_name,
                'node_count': len(nodes),
                'nodes': nodes,
                'node_stats': node_stats,  # 新增：节点统计
                **traffic_info
            }
            
            return result
            
        except requests.RequestException as e:
            raise Exception(f"下载订阅失败: {str(e)}")
        except Exception as e:
            raise Exception(f"解析订阅失败: {str(e)}")
    
    def _download_subscription(self, url):
        """
        下载订阅内容（可选使用代理）
        
        Args:
            url: 订阅链接
            
        Returns:
            Response: HTTP 响应对象
        """
        # 伪装成 Clash 客户端，以便服务器返回流量信息
        headers = {
            'User-Agent': 'ClashForAndroid/2.5.12'
        }
        
        response = requests.get(
            url,
            headers=headers,
            proxies=self.proxies,  # 如果 use_proxy=False，这里会是 None
            timeout=30,
            verify=False  # 跳过 SSL 验证，支持自签证书
        )
        response.raise_for_status()
        return response
    
    def _parse_traffic_info(self, headers):
        """
        从响应头解析流量信息
        
        Args:
            headers: HTTP 响应头
            
        Returns:
            dict: 流量信息字典
        """
        traffic_info = {}
        
        # 查找 subscription-userinfo 头
        userinfo = headers.get('subscription-userinfo', '')
        
        if userinfo:
            # 解析格式: upload=xxx; download=xxx; total=xxx; expire=xxx
            parts = userinfo.split(';')
            for part in parts:
                part = part.strip()
                if '=' in part:
                    key, value = part.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key in ['upload', 'download', 'total']:
                        traffic_info[key] = int(value)
                    elif key == 'expire':
                        try:
                            expire_timestamp = int(value)
                            expire_date = datetime.fromtimestamp(expire_timestamp)
                            traffic_info['expire_time'] = expire_date.strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            pass
            
            # 计算已用和剩余流量
            if 'upload' in traffic_info and 'download' in traffic_info:
                traffic_info['used'] = traffic_info['upload'] + traffic_info['download']
            
            if 'total' in traffic_info and 'used' in traffic_info:
                traffic_info['remaining'] = traffic_info['total'] - traffic_info['used']
                
                # 计算使用百分比
                if traffic_info['total'] > 0:
                    traffic_info['usage_percent'] = (traffic_info['used'] / traffic_info['total']) * 100
        
        return traffic_info
    
    def _parse_nodes(self, content):
        """
        解析节点信息（支持 Base64 和 Clash YAML 两种格式）
        
        Args:
            content: 订阅内容
            
        Returns:
            list: 节点列表
        """
        nodes = []
        
        # 检测是否为 Clash YAML 配置
        if content.strip().startswith('#') or 'proxies:' in content[:1000] or 'proxy-groups:' in content[:1000]:
            # 解析 Clash YAML 配置
            try:
                config = yaml.safe_load(content)
                if config and 'proxies' in config:
                    for proxy in config['proxies']:
                        if isinstance(proxy, dict):
                            node = {
                                'name': proxy.get('name', '未知节点'),
                                'protocol': proxy.get('type', 'unknown').lower(),
                                'server': proxy.get('server', ''),
                                'port': proxy.get('port', 0)
                            }
                            nodes.append(node)
                return nodes
            except Exception as e:
                # YAML 解析失败，尝试 Base64
                pass
        
        try:
            # 尝试 Base64 解码
            decoded_content = base64.b64decode(content).decode('utf-8')
        except:
            # 如果解码失败，使用原始内容
            decoded_content = content
        
        # 按行分割
        lines = decoded_content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 识别不同协议的节点
            node_info = self._parse_node_line(line)
            if node_info:
                nodes.append(node_info)
        
        return nodes
    
    def _parse_node_line(self, line):
        """
        解析单个节点行
        
        Args:
            line: 节点配置行
            
        Returns:
            dict: 节点信息，如果无法解析则返回 None
        """
        # 支持的协议前缀
        protocols = ['vmess://', 'vless://', 'ss://', 'ssr://', 'trojan://', 'hysteria://', 'hysteria2://']
        
        for protocol in protocols:
            if line.startswith(protocol):
                # 提取节点名称（通常在 # 或 remarks 参数中）
                node_name = self._extract_node_name(line, protocol)
                
                return {
                    'protocol': protocol.replace('://', ''),
                    'name': node_name,
                    'raw': line
                }
        
        return None
    
    def _extract_node_name(self, line, protocol):
        """
        从节点配置中提取节点名称
        
        Args:
            line: 节点配置行
            protocol: 协议前缀
            
        Returns:
            str: 节点名称
        """
        # 方法 1: 从 # 后面提取
        if '#' in line:
            name = line.split('#', 1)[1]
            # URL 解码
            try:
                from urllib.parse import unquote
                name = unquote(name)
            except:
                pass
            return name.strip()
        
        # 方法 2: 从 remarks 参数提取（vmess 等）
        if protocol == 'vmess://':
            try:
                import json
                encoded = line.replace('vmess://', '')
                decoded = base64.b64decode(encoded).decode('utf-8')
                config = json.loads(decoded)
                if 'ps' in config:
                    return config['ps']
            except:
                pass
        
        return "未命名节点"
    
    def _extract_airport_name(self, nodes, url, headers=None):
        """
        提取机场名称
        
        Args:
            nodes: 节点列表
            url: 订阅链接
            headers: 响应头（可选）
            
        Returns:
            str: 机场名称
        """
        # 方法 1: 从响应头 Content-Disposition 提取文件名
        if headers:
            cd = headers.get('Content-Disposition', '')
            if cd:
                try:
                    filename = None
                    if "filename*=" in cd:
                        # 提取 filename*=UTF-8''xxx
                        part = cd.split("filename*=")[1].split(";")[0].strip()
                        if part.lower().startswith("utf-8''"):
                            encoded_name = part[7:]
                            filename = unquote(encoded_name)
                    elif "filename=" in cd:
                        # 提取 filename="xxx"
                        filename = cd.split("filename=")[1].split(";")[0].strip('"')
                    
                    if filename:
                        # 移除扩展名
                        name = re.sub(r'\.(yaml|yml|txt|conf)$', '', filename, flags=re.IGNORECASE)
                        # 移除常见的括号包裹的内容（如果是纯修饰性的）
                        # 但对于【69云】这种，我们希望保留或提取核心部分
                        # 这里直接返回清理后的文件名，通常就是机场名
                        return name.strip()
                except:
                    pass
        
        if not nodes:
            return "未知机场"
        
        # 方法 2: 从节点名称中提取公共前缀
        node_names = [node['name'] for node in nodes if node.get('name')]
        
        if node_names:
            # 查找常见的机场名称模式
            # 例如: "XXX机场 - 香港01", "XXX机场 - 日本02"
            common_patterns = []
            
            for name in node_names:
                # 尝试提取 "-" 前的部分
                if '-' in name:
                    prefix = name.split('-')[0].strip()
                    common_patterns.append(prefix)
                elif '|' in name:
                    prefix = name.split('|')[0].strip()
                    common_patterns.append(prefix)
            
            if common_patterns:
                # 找出最常见的前缀
                from collections import Counter
                most_common = Counter(common_patterns).most_common(1)
                if most_common:
                    return most_common[0][0]
        
        # 方法 2: 从 URL 中提取域名
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc
            # 移除常见的子域名
            domain = re.sub(r'^(www\.|api\.|sub\.)', '', domain)
            return domain
        except:
            pass
        
        return "未知机场"
    
    def _analyze_nodes(self, nodes):
        """
        分析节点统计信息
        
        Args:
            nodes: 节点列表
            
        Returns:
            dict: 统计信息（国家/地区、协议分布）
        """
        from collections import Counter
        
        # 统计协议
        protocols = [node.get('protocol', 'unknown') for node in nodes]
        protocol_stats = dict(Counter(protocols))
        
        # 统计国家/地区
        countries = []
        country_keywords = {
            '香港': ['香港', 'HK', 'Hong Kong', 'Hongkong'],
            '台湾': ['台湾', 'TW', 'Taiwan'],
            '日本': ['日本', 'JP', 'Japan'],
            '美国': ['美国', 'US', 'USA', 'America'],
            '新加坡': ['新加坡', 'SG', 'Singapore'],
            '韩国': ['韩国', 'KR', 'Korea'],
            '英国': ['英国', 'UK', 'Britain'],
            '德国': ['德国', 'DE', 'Germany'],
            '法国': ['法国', 'FR', 'France'],
            '加拿大': ['加拿大', 'CA', 'Canada'],
            '澳大利亚': ['澳大利亚', 'AU', 'Australia'],
            '俄罗斯': ['俄罗斯', 'RU', 'Russia'],
            '印度': ['印度', 'IN', 'India'],
            '荷兰': ['荷兰', 'NL', 'Netherlands'],
            '土耳其': ['土耳其', 'TR', 'Turkey'],
        }
        
        for node in nodes:
            node_name = node.get('name', '')
            matched = False
            
            for country, keywords in country_keywords.items():
                for keyword in keywords:
                    if keyword in node_name:
                        countries.append(country)
                        matched = True
                        break
                if matched:
                    break
            
            if not matched:
                countries.append('其他')
        
        country_stats = dict(Counter(countries))
        
        return {
            'protocols': protocol_stats,
            'countries': country_stats
        }

