"""
订阅链接解析模块
负责下载、解析和提取订阅信息
"""

import base64
import re
import yaml
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime
import math

from core import node_extractor as ip_extractor
from core import geo_service


class SubscriptionParser:
    """订阅解析器"""
    
    def __init__(self, proxy_port=7890, use_proxy=False, session=None):
        """
        初始化解析器
        
        Args:
            proxy_port: 代理端口，默认 7890
            use_proxy: 是否使用代理，默认 False
            session: 复用的 aiohttp.ClientSession 对象
        """
        self.proxy_port = proxy_port
        self.use_proxy = use_proxy
        
        if use_proxy:
            self.proxy_url = f'http://127.0.0.1:{proxy_port}'
        else:
            self.proxy_url = None

        self.session = session
    
    async def parse(self, url):
        """
        解析订阅链接 (Async)
        
        Args:
            url: 订阅链接
            
        Returns:
            dict: 包含订阅信息的字典
        """
        try:
            # 下载订阅内容
            response_text, response_headers = await self._download_subscription(url)
            
            # 使用高级鉴伪（防机场跑路的拦截页面 200 OK）
            if self._is_pseudo_200_response(response_text, response_headers):
                raise Exception("检测到伪装的存活页面(可能服务商已跑路或节点全倒)，判定为失效源")
            
            # 解析流量信息（从响应头）
            traffic_info = self._parse_traffic_info(response_headers)
            
            # 解析节点信息
            nodes = self._parse_nodes(response_text)
            
            # 提取机场名称 (多维度：响应头、文件头注释、路径解析)
            airport_name = self._extract_airport_name(nodes, url, response_headers, response_text)

            
            # 统计节点信息
            node_stats = await self._analyze_nodes(nodes)
            
            # 如果节点数为 0，视为订阅失效或无法解析
            if len(nodes) == 0:
                raise Exception("未解析到任何有效节点（可能无流量或链接失效）")
                
            # 组合结果 (低内存优化：不再保存所有的原始节点配置，只需保存统计)
            result = {
                'name': airport_name,
                'node_count': len(nodes),
                'node_stats': node_stats,  # 新增：节点统计
                **traffic_info
            }
            
            return result
            
        except aiohttp.ClientError as e:
            raise Exception(f"下载订阅失败: {str(e)}")
        except Exception as e:
            raise Exception(f"解析订阅失败: {str(e)}")
    
    async def _download_subscription(self, url):
        """
        下载订阅内容（带重试机制，Async）
        
        Args:
            url: 订阅链接
            
        Returns:
            tuple: (text, headers字典)
        """
        from utils.retry_utils import async_retry_on_failure
        import aiohttp
        
        # 模拟 Clash Verge 客户端指纹，诱导更多机场返回详细 Metadata 响应头
        headers = {
            'User-Agent': 'Clash-verge/1.3.8 (Windows NT 10.0; Win64; x64) AppleWebkit/537.36',
            'Accept': '*/*'
        }
        
        # 确保有可用的 session
        session_to_use = self.session
        close_session = False
        if session_to_use is None:
            connector = aiohttp.TCPConnector(limit=10)
            session_to_use = aiohttp.ClientSession(connector=connector)
            close_session = True
            
        @async_retry_on_failure(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
        async def _fetch():
            async with session_to_use.get(
                url,
                headers=headers,
                proxy=self.proxy_url,
                timeout=aiohttp.ClientTimeout(total=30),
                ssl=False  # 跳过 SSL 验证，支持自签证书
            ) as response:
                response.raise_for_status()
                text = await response.text()
                # 转换 headers 为常规字典进行大小写不敏感匹配
                resp_headers = {k.lower(): v for k, v in response.headers.items()}
                return text, resp_headers
        
        try:
            return await _fetch()
        finally:
            if close_session:
                await session_to_use.close()
        
    def _shannon_entropy(self, data: str) -> float:
        """计算文本数据的香农信息熵"""
        if not data:
            return 0
        entropy = 0
        for x in set(data):
            p_x = float(data.count(x)) / len(data)
            if p_x > 0:
                entropy += - p_x * math.log(p_x, 2)
        return entropy

    def _is_pseudo_200_response(self, content: str, headers: dict) -> bool:
        """强化版特征库级：联合拦截流氓拦截页面的伪 200 问题"""
        content_lower = content.lower()
        
        # 策略 1: HTTP Header 指纹
        content_type = headers.get('Content-Type', '').lower()
        if 'text/html' in content_type:
            # 绝大多数订阅是纯文本或二进制，若返回 HTML 且包含常见错误词，判定为伪活
            if any(x in content_lower for x in ['error', 'forbidden', 'blocked', 'firewall', '拦截', '参数错误', '未找到']):
                return True

        # 策略 2: 极短内容的特征识别
        if 0 < len(content) < 50:
            if any(x in content_lower for x in ['forbidden', 'not found', 'error']):
                return True
            
        # 策略 3: 信息熵校验。标准 Base64 编码的订阅节点具备极高的熵值 (> 4.8)
        # 而运营商拦截页、WAF 盾页面的熵值往往偏低 (< 4.2)
        if len(content) > 100:
            entropy = self._shannon_entropy(content)
            # 专家阈值设定：4.25 是区分压缩内容与自然语言报错页的黄金分割点
            if entropy < 4.25:
                # 二次确认：如果熵值低且包含大量 HTML 标签，必死无疑
                if re.search(r"<(html|head|body|script|div|a)", content_lower):
                    return True

        return False
    
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
        MAX_NODES = 300  # 内存优化：强制最大解析节点数，防 OOM
        
        # 检测是否为 Clash YAML 配置
        if content.strip().startswith('#') or 'proxies:' in content[:5000] or 'proxy-groups:' in content[:5000]:
            # 内存优化：直接截断超过 300KB 的文件部分（通常够存几千个节点了）
            if len(content) > 300 * 1024:
                # 尽量截取在行尾，防止切断 yaml 导致抛错
                truncate_idx = content.rfind('\n', 0, 300 * 1024)
                if truncate_idx != -1:
                    content = content[:truncate_idx]
                else:
                    content = content[:300 * 1024]
                
            try:
                config = yaml.safe_load(content)
                if config and 'proxies' in config:
                    for proxy in config['proxies']:
                        if len(nodes) >= MAX_NODES:
                            break
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
        
        # 尝试 Base64 解码 (增强版：支持自动补位、URL-safe 格式)
        decoded_content = content
        cleaned_content = content.replace('\n', '').replace('\r', '').replace(' ', '').strip()
        
        # 尝试 Base64 解码的闭包
        def try_b64_decode(data):
            # 补齐末尾的 '='
            missing_padding = len(data) % 4
            if missing_padding:
                data += '=' * (4 - missing_padding)
            
            try:
                # 尝试标准解码
                return base64.b64decode(data).decode('utf-8', errors='ignore')
            except:
                try:
                    # 尝试 URL-safe 解码
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                except:
                    return None

        temp_decoded = try_b64_decode(cleaned_content)
        if temp_decoded:
            decoded_content = temp_decoded
        
        # 按行分割
        lines = decoded_content.strip().split('\n')
        
        for line in lines:
            if len(nodes) >= MAX_NODES:
                break
                
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
        """
        protocols = ['vmess://', 'vless://', 'ss://', 'ssr://', 'trojan://', 'hysteria://', 'hysteria2://']
        for protocol in protocols:
            if line.startswith(protocol):
                node_name = self._extract_node_name(line, protocol)
                return {
                    'protocol': protocol.replace('://', ''),
                    'name': node_name,
                    'raw': line
                }
        return None

    def _extract_node_name(self, line, protocol):
        """从节点配置中提取节点名称"""
        if '#' in line:
            name = line.split('#', 1)[1]
            try: return unquote(name).strip()
            except: return name.strip()
        
        if protocol == 'vmess://':
            try:
                import json
                encoded = line.replace('vmess://', '')
                # 处理可能存在的 padding
                missing_padding = len(encoded) % 4
                if missing_padding: encoded += '=' * (4 - missing_padding)
                decoded = base64.b64decode(encoded).decode('utf-8')
                config = json.loads(decoded)
                if 'ps' in config: return config['ps']
            except: pass
        return "未命名节点"

    def _extract_airport_name(self, nodes, url, headers=None, content=None):
        """
        全维度机场名称提取 (对齐顶级客户端识别策略)
        """
        BAD_KEYWORDS = [
            '过期', '到期', '流量', '剩余', 'GB', 'TB', '官网', '发布', '地址', 
            '通知', '维护', '重置', '套餐', '客服', '注册', '新加坡', '美国', '香港', 
            '台湾', '日本', '韩国', '节点', '测速', 'v1', 'client', 'subscribe', 'api', 'sub'
        ]
        COMMON_TLDS = ['com', 'net', 'org', 'me', 'io', 'cc', 'top', 'xyz', 'shop', 'info', 'site', 'link', 'cloud', 'vip', 'best']

        def is_trash(s):
            if not s or len(s) < 2: return True
            if s.isdigit() or len(s) > 30: return True 
            if not re.search(r'[\u4e00-\u9fa5]', s):
                has_digit = any(c.isdigit() for c in s)
                has_upper = any(c.isupper() for c in s)
                has_lower = any(c.islower() for c in s)
                if len(s) > 6 and has_digit and has_upper and has_lower: return True
                if len(s) > 6 and self._shannon_entropy(s) > 3.0: return True
            return any(kw in s for kw in BAD_KEYWORDS)

        # 1. 响应头解析 (profile-title / Content-Disposition)
        if headers:
            raw_title = headers.get('profile-title') or headers.get('x-airport-name') or headers.get('x-profile-name')
            if raw_title:
                # [核心修复] 彻底解决 UTF-8"魔戒 这种非标编码前缀干扰
                raw_title = re.sub(r'^(?i)utf-8[\'"]*', '', raw_title.strip())
                title = unquote(raw_title).strip().strip('"').strip("'").strip()
                if not is_trash(title): return title

            cd = headers.get('content-disposition', '')
            if 'filename' in cd:
                try:
                    m = re.search(r"filename\*=(?:utf-8['\"]*)?(.+?)(?:;|$)", cd, re.IGNORECASE)
                    if not m: m = re.search(r"filename=['\"]?(.+?)['\"]?(?:;|$)", cd, re.IGNORECASE)
                    if m:
                        fn = unquote(m.group(1)).strip().strip('"').strip("'")
                        name = re.sub(r'\.(yaml|yml|txt|conf)$', '', fn, flags=re.IGNORECASE)
                        if not is_trash(name): return name
                except: pass

        # 2. 文件内容扫描
        if content:
            sample = content[:500]
            if sample.startswith('#') or 'proxies:' in sample:
                first_line = sample.split('\n', 1)[0].strip()
                if first_line.startswith('#'):
                    comment_title = first_line.lstrip('# ').strip()
                    if comment_title and not is_trash(comment_title):
                        comment_title = re.sub(r'[ \-(](v\d+|20\d{2}|update|check).*$', '', comment_title, flags=re.IGNORECASE)
                        return comment_title

        # 3. 节点前缀深度分析 (针对 SakuraCat 这类隐性机场)
        if nodes:
            prefixes = []
            for n in nodes:
                name = n.get('name', '')
                m = re.match(r'^([^| \-—:：/]+)', name)
                if m:
                    p = m.group(1).strip()
                    if p and not is_trash(p): prefixes.append(p)
            
            if prefixes:
                from collections import Counter
                most = Counter(prefixes).most_common(1)
                # 判定阈值：只要有 25% 以上的节点带此共性且非地名，就判定为品牌名
                if most and most[0][1] > (len(nodes) * 0.25):
                    return most[0][0]

        # 4. URL 路径解析
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        for part in reversed(path_parts):
            clean = re.sub(r'\.(yaml|yml|txt|conf)$', '', part, flags=re.IGNORECASE)
            if not is_trash(clean): return clean

        # 5. 域名提取与兜底
        try:
            domain = parsed.netloc.split(':')[0]
            domain_parts = [p for p in domain.split('.') if p.lower() not in COMMON_TLDS and p.lower() not in ['api', 'sub', 'www', 'cdn']]
            if domain_parts:
                brand = domain_parts[-1]
                if not is_trash(brand): return brand
        except: pass

        return "未知机场"




    
    async def _analyze_nodes(self, nodes):
        """
        分析节点统计信息(使用真实IP地理位置查询，全异步版本)

        Args:
            nodes: 节点列表

        Returns:
            dict: 统计信息(国家/地区、协议分布、详细位置)
        """
        from collections import Counter
        import config
        import asyncio

        # 统计协议
        protocols = [node.get('protocol', 'unknown') for node in nodes]
        protocol_stats = dict(Counter(protocols))

        # 地理位置查询（受 ENABLE_GEO_LOOKUP 开关控制）
        if not config.ENABLE_GEO_LOOKUP:
            # 关闭地理查询：纯关键词匹配，零网络开销
            countries = [self._match_country_by_keyword(n.get('name', '')) for n in nodes]
            return {
                'protocols': protocol_stats,
                'countries': dict(Counter(countries)),
                'locations': []
            }

        from core.node_extractor import NodeIPExtractor
        from core.geo_service import GeoLocationService
        
        geo_client = GeoLocationService()

        MAX_GEO_QUERIES = config.MAX_GEO_QUERIES

        # 第一步：提取每个节点的 IP（串行，纯内存操作，无 IO）
        node_ip_pairs = []
        for node in nodes:
            ip = ip_extractor.NodeIPExtractor.extract_ip(node)
            if ip and ip_extractor.NodeIPExtractor.is_valid_ip(ip):
                node_ip_pairs.append((node, ip))
            else:
                node_ip_pairs.append((node, None))

        # 第二步：并发查询需要真实 IP 查询的节点（最多 MAX_GEO_QUERIES 个）
        geo_nodes = [(node, ip) for node, ip in node_ip_pairs if ip is not None][:MAX_GEO_QUERIES]
        geo_results = {}  # ip -> location

        if geo_nodes:
            unique_ips = list({ip for _, ip in geo_nodes})
            # 采用 asyncio.gather 代替 ThreadPoolExecutor
            tasks = [geo_client.get_location(ip) for ip in unique_ips]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for ip, res in zip(unique_ips, results):
                if isinstance(res, Exception):
                    geo_results[ip] = None
                else:
                    geo_results[ip] = res

        # 第三步：组合结果，保持原节点顺序
        countries = []
        locations_detail = []
        country_detail_count = Counter()
        geo_query_used = 0

        for node, ip in node_ip_pairs:
            country = None
            detail_obj = None

            if ip and geo_query_used < MAX_GEO_QUERIES:
                geo_query_used += 1
                location = geo_results.get(ip)
                if location:
                    country = location['country']
                    countries.append(country)

                    if country_detail_count[country] < 3:
                        detail_obj = {
                            'name': node.get('name', '未知'),
                            'country': country,
                            'city': location['city'],
                            'isp': location['isp'],
                            'country_code': location['country_code'],
                            'flag': geo_client.get_country_flag(location['country_code'])
                        }

            if not country:
                # IP 查询失败，回退到关键词匹配
                node_name = node.get('name', '')
                country = self._match_country_by_keyword(node_name)
                countries.append(country)

                if country_detail_count[country] < 3:
                    detail_obj = {
                        'name': node.get('name', '未知'),
                        'country': country,
                        'city': '未知',
                        'isp': '未知',
                        'country_code': '',
                        'flag': '🌐'
                    }

            if detail_obj:
                locations_detail.append(detail_obj)
                country_detail_count[country] += 1

        country_stats = dict(Counter(countries))

        return {
            'protocols': protocol_stats,
            'countries': country_stats,
            'locations': locations_detail
        }
    
    def _match_country_by_keyword(self, node_name: str) -> str:
        """通过关键词匹配国家(备用方案)"""
        country_keywords = {
            '香港': ['香港', 'HK', 'Hong Kong', 'Hongkong'],
            '台湾': ['台湾', 'TW', 'Taiwan'],
            '日本': ['日本', 'JP', 'Japan'],
            '美国': ['美国', 'US', 'USA', 'America'],
            '新加坡': ['新加坡', 'SG', 'Singapore'],
            '韩国': ['韩国', 'KR', 'Korea'],
        }
        
        for country, keywords in country_keywords.items():
            if any(kw in node_name for kw in keywords):
                return country
        
        return '其他'







