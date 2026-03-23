#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SS协议节点转换工具
支持SS协议txt文件与yaml格式的双向转换
"""
from __future__ import annotations

import base64
import re
import json
import yaml
from urllib.parse import urlparse, parse_qs, unquote
from typing import List, Dict, Optional, Any
import argparse
import sys
import binascii
from core.models import ProxyNode


class SSNodeConverter:
    """SS节点转换器类"""
    
    def __init__(self):
        self.nodes = []
        self.remarks = ""
        self.status = ""
    
    def parse_vmess_url(self, vmess_url: str) -> Optional[ProxyNode]:
        """
        解析单条 Vmess 协议 URL
        """
        try:
            if not vmess_url.startswith('vmess://'):
                return None
            
            encoded_part = vmess_url[8:]
            # Base64 解码需要补齐等号
            padding = len(encoded_part) % 4
            if padding:
                encoded_part += '=' * (4 - padding)
            
            decoded = base64.b64decode(encoded_part).decode('utf-8')
            config = json.loads(decoded)
            
            # 基础信息映射（兼容主流格式）
            node = {
                'name': config.get('ps', '未命名节点'),
                'type': 'vmess',
                'server': config.get('add'),
                'port': int(config.get('port', 0)),
                'uuid': config.get('id'),
                'alterId': int(config.get('aid', 0)),
                'cipher': config.get('type', 'auto'),
                'udp': True,
                'tls': config.get('tls') == 'tls' or config.get('tls') == True
            }
            
            # 处理传输协议
            net = config.get('net')
            if net == 'ws':
                node['network'] = 'ws'
                node['ws-opts'] = {
                    'path': config.get('path', '/'),
                    'headers': {'Host': config.get('host', '')}
                }
            elif net == 'h2':
                node['network'] = 'h2'
                node['h2-opts'] = {
                    'path': config.get('path', '/'),
                    'host': [config.get('host', '')]
                }
            
            if config.get('sni'):
                node['servername'] = config.get('sni')
            elif config.get('host') and node['tls']:
                node['servername'] = config.get('host')
                
            return node
        except (json.JSONDecodeError, ValueError, KeyError, binascii.Error) as e:
            print(f"解析 Vmess URL 失败: {e}")
            return None

    def parse_trojan_url(self, trojan_url: str) -> Optional[ProxyNode]:
        """
        解析单条 Trojan 协议 URL
        """
        try:
            if not trojan_url.startswith('trojan://'):
                return None
            
            parsed = urlparse(trojan_url)
            node_name = unquote(parsed.fragment) if parsed.fragment else "未命名 Trojan 节点"
            query = parse_qs(parsed.query)
            
            node = {
                'name': node_name,
                'type': 'trojan',
                'server': parsed.hostname,
                'port': int(parsed.port) if parsed.port else 443,
                'password': parsed.username,
                'udp': True,
                'sni': query.get('sni', [parsed.hostname])[0],
                'skip-cert-verify': query.get('allowInsecure', ['0'])[0] == '1'
            }
            return node
        except (ValueError, KeyError, IndexError) as e:
            print(f"解析 Trojan URL 失败: {e}")
            return None

    def parse_vless_url(self, vless_url: str) -> Optional[ProxyNode]:
        """
        解析单条 VLESS 协议 URL
        格式: vless://uuid@server:port?type=...&security=...#name
        """
        try:
            if not vless_url.startswith('vless://'):
                return None

            parsed   = urlparse(vless_url)
            name     = unquote(parsed.fragment) if parsed.fragment else "未命名 VLESS 节点"
            query    = parse_qs(parsed.query)
            # parse_qs 返回列表，取第一个元素
            def _q(k, d=''):
                return query.get(k, [d])[0]

            node = {
                'name':              name,
                'type':              'vless',
                'server':            parsed.hostname,
                'port':              int(parsed.port) if parsed.port else 443,
                'uuid':              parsed.username or '',
                'udp':               True,
                'tls':               _q('security') in ('tls', 'reality', 'xtls'),
                'network':           _q('type', 'tcp'),
                'skip-cert-verify':  _q('allowInsecure', '0') == '1',
            }

            # SNI / servername
            sni = _q('sni') or _q('serverName')
            if sni:
                node['servername'] = sni

            # flow （XTLS）
            flow = _q('flow')
            if flow:
                node['flow'] = flow

            # WebSocket 传输
            if node['network'] == 'ws':
                node['ws-opts'] = {
                    'path':    _q('path', '/'),
                    'headers': {'Host': _q('host')},
                }
            elif node['network'] == 'grpc':
                node['grpc-opts'] = {'grpc-service-name': _q('serviceName')}

            # Reality 公钥指纹
            pbk = _q('pbk')
            if pbk:
                node['reality-opts'] = {
                    'public-key': pbk,
                    'short-id':   _q('sid'),
                }

            return node
        except (ValueError, KeyError, IndexError) as e:
            print(f"解析 VLESS URL 失败: {e}")
            return None

    def parse_ss_url(self, ss_url: str) -> Optional[ProxyNode]:
        """
        解析单个SS协议URL
        
        支持以下三种格式:
        1. SIP002 标准格式: ss://BASE64(method:password)@host:port[/][?params][#name]
        2. 旧式整体Base64格式: ss://BASE64(整个URI信息)[#name]
        3. 明文无Base64格式: ss://method:password@host:port[#name]
        
        Args:
            ss_url: SS协议URL字符串
            
        Returns:
            包含节点信息的字典,解析失败返回None
        """
        try:
            # 移除ss://前缀
            if not ss_url.startswith('ss://'):
                return None
            
            ss_body = ss_url[5:]
            
            # 分离节点名称(#后面的部分)
            node_name = "未命名节点"
            if '#' in ss_body:
                ss_body, raw_name = ss_body.split('#', 1)
                node_name = unquote(raw_name).strip()
            
            # 至此 ss_body 已不含 #name 部分，去除尾部空白
            ss_body = ss_body.strip()
            
            # 分离查询参数（支持 ? 和 /? 两种形式）
            query_params = {}
            if '?' in ss_body:
                ss_body, query_string = ss_body.split('?', 1)
                query_params = parse_qs(query_string)
                # 将列表值转换为单个值
                query_params = {k: v[0] if isinstance(v, list) and len(v) > 0 else v 
                              for k, v in query_params.items()}
            
            # 去除末尾的斜杠（SIP002 格式端口后可能带 /）
            ss_body = ss_body.rstrip('/')
            
            server = None
            port = None
            method = None
            password = None
            plugin_info = ""
            
            # -------- 格式A/B: 含 @ 符号（SIP002 或明文格式） --------
            if '@' in ss_body:
                encoded_part, server_part = ss_body.rsplit('@', 1)
                
                # 解析服务器和端口，端口字符串要先清除可能残留的斜杠
                if ':' in server_part:
                    server, port_str = server_part.rsplit(':', 1)
                    port_str = port_str.rstrip('/').strip()
                    try:
                        port = int(port_str)
                    except ValueError:
                        return None
                else:
                    return None
                
                # 优先尝试 Base64 解码 encoded_part（SIP002 格式）
                decoded_str = None
                try:
                    padding = len(encoded_part) % 4
                    padded = encoded_part + '=' * (4 - padding) if padding else encoded_part
                    decoded_bytes = base64.b64decode(padded)
                    decoded_str = decoded_bytes.decode('utf-8')
                except binascii.Error:
                    pass
                
                if decoded_str and ':' in decoded_str:
                    # Base64 解码成功，格式为 method:password[:plugin_info]
                    parts = decoded_str.split(':', 2)
                    method = parts[0]
                    password = parts[1] if len(parts) > 1 else ""
                    plugin_info = parts[2] if len(parts) > 2 else ""
                elif ':' in encoded_part:
                    # 明文格式：method:password（无 Base64 编码）
                    parts = encoded_part.split(':', 1)
                    method = parts[0]
                    password = parts[1]
                else:
                    return None
                    
            else:
                # -------- 格式C: 旧式整体 Base64 格式 --------
                # 整段 ss_body 是 Base64 编码，解码后是 method:password@server:port
                try:
                    padding = len(ss_body) % 4
                    padded = ss_body + '=' * (4 - padding) if padding else ss_body
                    decoded_str = base64.b64decode(padded).decode('utf-8')
                    if '@' in decoded_str:
                        cred_part, addr_part = decoded_str.rsplit('@', 1)
                        if ':' in cred_part:
                            method, password = cred_part.split(':', 1)
                        if ':' in addr_part:
                            server, port_str = addr_part.rsplit(':', 1)
                            port = int(port_str.rstrip('/').strip())
                    else:
                        return None
                except binascii.Error:
                    return None
            
            # 基本信息校验
            if not all([server, port, method, password]):
                return None
            
            # 构建节点字典
            node = {
                'name': node_name,
                'type': 'ss',
                'server': server,
                'port': port,
                'cipher': method,
                'password': password,
            }
            
            # 添加可选参数
            if 'udp' in query_params:
                node['udp'] = query_params['udp'] == '1'
            
            if 'tfo' in query_params:
                node['tfo'] = query_params['tfo'] == '1'
            
            if 'group' in query_params:
                try:
                    group = base64.b64decode(query_params['group']).decode('utf-8')
                    node['group'] = group
                except binascii.Error:
                    pass
            
            if plugin_info:
                node['plugin-info'] = plugin_info
            
            return node
            
        except (ValueError, IndexError, binascii.Error):
            # 静默失败：解析失败的行层出错很常见（乱码行、不支持的变体等），
            # 打印会在批量解析时屁屏，直接返回 None 即可
            return None
    
    def iter_txt_file(self, file_path: str):
        """
        以流式生成器逐行解析txt文件中的协议链接，极大降低内存占用。
        
        Args:
            file_path: txt文件路径
        Yields:
            解析出的 ProxyNode 字典
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                first_line_checked = False
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue

                    if not first_line_checked:
                        first_line_checked = True
                        if line.startswith('REMARKS='):
                            remarks_match = re.search(
                                r'REMARKS=(.+?)(?:\s+STATUS=(.+))?$', line)
                            if remarks_match:
                                self.remarks = remarks_match.group(1)
                                self.status  = remarks_match.group(2) or ''
                            continue

                    node = None
                    if line.startswith('ss://'):
                        node = self.parse_ss_url(line)
                    elif line.startswith('ssr://'):
                        node = self.parse_ssr_url(line)
                    elif line.startswith('vmess://'):
                        node = self.parse_vmess_url(line)
                    elif line.startswith('trojan://'):
                        node = self.parse_trojan_url(line)
                    elif line.startswith('vless://'):
                        node = self.parse_vless_url(line)

                    if node:
                        yield node
        except Exception as e:
            print(f"读取txt文件失败: {e}")

    def parse_txt_file(self, file_path: str) -> bool:
        """
        兼容遗留 API: 将所有的生成器结果收集至 self.nodes 列表中。
        """
        try:
            new_nodes = list(self.iter_txt_file(file_path))
            self.nodes.extend(new_nodes)
            print(f"成功解析 {len(new_nodes)} 个节点")
            return len(new_nodes) > 0
        except Exception as e:
            print(f"解析txt文件失败: {e}")
            return False
    
    def to_yaml(self, output_file: str, full_config: bool = True) -> bool:
        """
        将节点导出为yaml格式
        
        Args:
            output_file: 输出yaml文件路径
            full_config: 是否生成包含代理组和规则的完整配置文件 (Expert Optimization)
            
        Returns:
            导出成功返回True,失败返回False
        """
        import os
        try:
            out_dir = os.path.dirname(os.path.abspath(output_file))
            os.makedirs(out_dir, exist_ok=True)

            if not full_config:
                yaml_data = {'proxies': self.nodes}
                if self.remarks or self.status:
                    yaml_data['metadata'] = {}
                    if self.remarks: yaml_data['metadata']['remarks'] = self.remarks
                    if self.status: yaml_data['metadata']['status'] = self.status
            else:
                # 专家级：生成生产环境可用的完整配置文件
                proxy_names = [n['name'] for n in self.nodes]
                yaml_data = {
                    'port': 7890,
                    'socks-port': 7891,
                    'allow-lan': True,
                    'mode': 'rule',
                    'log-level': 'info',
                    'external-controller': '127.0.0.1:9090',
                    'proxies': self.nodes,
                    'proxy-groups': [
                        {
                            'name': '🚀 节点选择',
                            'type': 'select',
                            'proxies': ['⚡ 自动选择', '🎯 全球直连'] + proxy_names
                        },
                        {
                            'name': '⚡ 自动选择',
                            'type': 'url-test',
                            'url': 'http://www.gstatic.com/generate_204',
                            'interval': 300,
                            'proxies': proxy_names
                        },
                        {
                            'name': '🎬 视频流媒体',
                            'type': 'select',
                            'proxies': ['🚀 节点选择', '⚡ 自动选择'] + proxy_names
                        },
                        {
                            'name': '📲 社交工具',
                            'type': 'select',
                            'proxies': ['🚀 节点选择', '🎯 全球直连'] + proxy_names
                        },
                        {
                            'name': '🍎 苹果服务',
                            'type': 'select',
                            'proxies': ['🎯 全球直连', '🚀 节点选择']
                        },
                        {
                            'name': '🛑 广告拦截',
                            'type': 'select',
                            'proxies': ['REJECT', 'DIRECT']
                        },
                        {
                            'name': '🎯 全球直连',
                            'type': 'select',
                            'proxies': ['DIRECT', 'REJECT']
                        }
                    ],
                    'rules': [
                        'DOMAIN-SUFFIX,google.com,🚀 节点选择',
                        'DOMAIN-KEYWORD,youtube,🎬 视频流媒体',
                        'DOMAIN-KEYWORD,netflix,🎬 视频流媒体',
                        'DOMAIN-KEYWORD,telegram,📲 社交工具',
                        'DOMAIN-SUFFIX,apple.com,🍎 苹果服务',
                        'DOMAIN-SUFFIX,icloud.com,🍎 苹果服务',
                        'MATCH,🚀 节点选择'
                    ]
                }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_data, f, allow_unicode=True, 
                         default_flow_style=False, sort_keys=False)
            
            print(f"成功导出到yaml文件: {output_file}")
            return True
            
        except OSError as e:
            print(f"导出yaml文件失败(文件系统错误): {e}")
            return False
        except yaml.YAMLError as e:
            print(f"导出yaml文件失败(YAML序列化错误): {e}")
            return False
    
    def build_ss_url(self, node: Dict) -> Optional[str]:
        """
        从节点字典构建SS协议URL
        
        Args:
            node: 节点信息字典
            
        Returns:
            SS协议URL字符串,构建失败返回None
        """
        try:
            # 提取必要字段
            name = node.get('name', '未命名节点')
            server = node.get('server', '')
            port = node.get('port', 0)
            cipher = node.get('cipher', '')
            password = node.get('password', '')
            
            if not all([server, port, cipher, password]):
                print(f"节点 {name} 缺少必要字段")
                return None
            
            # 构建加密信息
            plugin_info = node.get('plugin-info', '')
            if plugin_info:
                encoded_str = f"{cipher}:{password}:{plugin_info}"
            else:
                encoded_str = f"{cipher}:{password}"
            
            # Base64编码
            encoded = base64.b64encode(encoded_str.encode('utf-8')).decode('utf-8')
            # 移除padding
            encoded = encoded.rstrip('=')
            
            # 构建查询参数
            query_parts = []
            
            if 'udp' in node:
                query_parts.append(f"udp={'1' if node['udp'] else '0'}")
            
            if 'tfo' in node:
                query_parts.append(f"tfo={'1' if node['tfo'] else '0'}")
            
            if 'group' in node:
                group_encoded = base64.b64encode(node['group'].encode('utf-8')).decode('utf-8')
                query_parts.append(f"group={group_encoded}")
            
            # 构建完整URL
            ss_url = f"ss://{encoded}@{server}:{port}/"
            
            if query_parts:
                ss_url += '?' + '&'.join(query_parts)
            
            # 添加节点名称(URL编码)
            from urllib.parse import quote
            ss_url += '#' + quote(name, safe='')
            
            return ss_url
            
        except (TypeError, ValueError) as e:
            print(f"构建SS URL失败: {e}")
            return None
    
    def parse_yaml_file(self, file_path: str) -> bool:
        """
        解析 yaml 文件

        Args:
            file_path: yaml 文件路径

        Returns:
            解析成功返回 True，失败返回 False
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                yaml_data = yaml.safe_load(f)

            # 防止空文件或格式错误导致 yaml_data 为 None/非 dict
            if not isinstance(yaml_data, dict):
                print("yaml 文件为空或格式不合法（顶层不是字典）")
                return False

            # 提取节点列表
            if 'proxies' not in yaml_data:
                print("yaml 文件中未找到 proxies 字段")
                return False

            self.nodes = yaml_data['proxies'] or []

            # 提取元数据
            if 'metadata' in yaml_data:
                self.remarks = yaml_data['metadata'].get('remarks', '')
                self.status  = yaml_data['metadata'].get('status', '')

            print(f"成功解析 {len(self.nodes)} 个节点")
            return len(self.nodes) > 0

        except OSError as e:
            print(f"读取 yaml 文件失败(文件系统错误): {e}")
            return False
        except yaml.YAMLError as e:
            print(f"读取 yaml 文件失败(YAML反序列化错误): {e}")
            return False

    
    def build_vmess_url(self, node: Dict) -> Optional[str]:
        """
        从节点字典构建 Vmess 协议 URL（vmess://BASE64_JSON）

        Args:
            node: 节点信息字典（type 必须为 'vmess'）

        Returns:
            vmess:// URL 字符串，构建失败返回 None
        """
        try:
            ws_opts = node.get('ws-opts', {})
            h2_opts = node.get('h2-opts', {})
            net = node.get('network', 'tcp')

            config = {
                'v':   '2',
                'ps':  node.get('name', '未命名节点'),
                'add': node.get('server', ''),
                'port': str(node.get('port', 0)),
                'id':  node.get('uuid', ''),
                'aid': str(node.get('alterId', 0)),
                'scy': node.get('cipher', 'auto'),
                'net': net,
                'type': 'none',
                'host': '',
                'path': '',
                'tls': 'tls' if node.get('tls') else '',
                'sni': node.get('servername', ''),
                'alpn': '',
            }

            if net == 'ws':
                config['path'] = ws_opts.get('path', '/')
                config['host'] = ws_opts.get('headers', {}).get('Host', '')
            elif net == 'h2':
                config['path'] = h2_opts.get('path', '/')
                hosts = h2_opts.get('host', [])
                config['host'] = hosts[0] if hosts else ''

            json_str = json.dumps(config, ensure_ascii=False, separators=(',', ':'))
            encoded = base64.b64encode(json_str.encode('utf-8')).decode('utf-8').rstrip('=')
            return f"vmess://{encoded}"
        except (TypeError, ValueError) as e:
            print(f"构建 Vmess URL 失败: {e}")
            return None

    def build_trojan_url(self, node: Dict) -> Optional[str]:
        """
        从节点字典构建 Trojan 协议 URL

        Args:
            node: 节点信息字典（type 必须为 'trojan'）

        Returns:
            trojan:// URL 字符串，构建失败返回 None
        """
        try:
            from urllib.parse import quote as _quote
            server   = node.get('server', '')
            port     = node.get('port', 443)
            password = node.get('password', '')
            name     = node.get('name', '未命名节点')
            sni      = node.get('sni', server)
            insecure = '1' if node.get('skip-cert-verify') else '0'

            if not all([server, port, password]):
                print(f"节点 {name} 缺少必要字段")
                return None

            url = f"trojan://{_quote(password, safe='')}@{server}:{port}"
            params = f"sni={_quote(sni)}&allowInsecure={insecure}"
            url += f"?{params}#{_quote(name, safe='')}"
            return url
        except (TypeError, ValueError) as e:
            print(f"构建 Trojan URL 失败: {e}")
            return None

    def build_vless_url(self, node: Dict) -> Optional[str]:
        """
        构建 VLESS 协议 URL
        格式: vless://uuid@server:port?type=...&security=...#name
        """
        try:
            from urllib.parse import quote as _quote, urlencode
            server = node.get('server', '')
            port   = node.get('port', 443)
            uuid   = node.get('uuid', '')
            name   = node.get('name', '未命名节点')
            if not all([server, port, uuid]):
                print(f"节点 {name} 缺少必要字段")
                return None

            params = {'type': node.get('network', 'tcp')}

            # 安全类型
            if node.get('tls'):
                params['security'] = 'tls'
            if node.get('reality-opts'):
                params['security'] = 'reality'
                params['pbk']      = node['reality-opts'].get('public-key', '')
                sid = node['reality-opts'].get('short-id')
                if sid:
                    params['sid'] = sid

            # SNI
            sni = node.get('servername', '')
            if sni:
                params['sni'] = sni

            # flow
            flow = node.get('flow', '')
            if flow:
                params['flow'] = flow

            # WebSocket
            if node.get('network') == 'ws':
                ws = node.get('ws-opts', {})
                params['path'] = ws.get('path', '/')
                host = ws.get('headers', {}).get('Host', '')
                if host:
                    params['host'] = host

            # gRPC
            if node.get('network') == 'grpc':
                params['serviceName'] = node.get('grpc-opts', {}).get('grpc-service-name', '')

            if node.get('skip-cert-verify'):
                params['allowInsecure'] = '1'

            qs = '&'.join(f"{k}={_quote(str(v), safe='')}" for k, v in params.items() if v)
            url = f"vless://{uuid}@{server}:{port}?{qs}#{_quote(name, safe='')}"
            return url
        except (TypeError, ValueError) as e:
            print(f"构建 VLESS URL 失败: {e}")
            return None

    def parse_ssr_url(self, ssr_url: str) -> Optional[ProxyNode]:
        """
        解析单条 SSR (ShadowsocksR) 协议 URL
        格式: ssr://BASE64(host:port:protocol:method:obfs:base64pass/?obfsparam=base64param&protoparam=base64param&remarks=base64remarks&group=base64group)
        """
        try:
            if not ssr_url.startswith('ssr://'):
                return None
            
            encoded_part = ssr_url[6:].strip()
            # Base64 解码
            def b64_decode(data):
                data = data.replace('-', '+').replace('_', '/')
                padding = len(data) % 4
                if padding:
                    data += '=' * (4 - padding)
                return base64.b64decode(data).decode('utf-8', errors='ignore')

            decoded = b64_decode(encoded_part)
            
            # 分离主要部分和参数部分
            main_part, param_part = decoded.split('/?', 1) if '/?' in decoded else (decoded, "")
            
            # 解析主要部分: host:port:protocol:method:obfs:base64pass
            main_fields = main_part.split(':')
            if len(main_fields) < 6:
                return None
            
            server = main_fields[0]
            port = int(main_fields[1])
            protocol = main_fields[2]
            method = main_fields[3]
            obfs = main_fields[4]
            password = b64_decode(main_fields[5])
            
            # 解析参数部分
            params = {}
            if param_part:
                for kv in param_part.split('&'):
                    if '=' in kv:
                        k, v = kv.split('=', 1)
                        params[k] = b64_decode(v)
            
            node_name = params.get('remarks', '未命名 SSR 节点')
            group = params.get('group', 'ShadowsocksR')
            
            node = {
                'name': node_name,
                'type': 'ssr',
                'server': server,
                'port': port,
                'password': password,
                'cipher': method,
                'protocol': protocol,
                'protocol-param': params.get('protoparam', ''),
                'obfs': obfs,
                'obfs-param': params.get('obfsparam', ''),
                'group': group,
                'udp': True
            }
            return node
        except (ValueError, IndexError, TypeError, binascii.Error) as e:
            print(f"解析 SSR URL 失败: {e}")
            return None

    def build_ssr_url(self, node: Dict) -> Optional[str]:
        """
        从节点字典构建 SSR 协议 URL
        """
        try:
            def b64_encode(data):
                # SSR 强烈建议使用带填充的标准 Base64 以保证兼容性
                if not data: return ""
                return base64.b64encode(data.encode('utf-8')).decode('utf-8')

            server = node.get('server', '')
            port = str(node.get('port', 0))
            protocol = node.get('protocol', 'origin')
            method = node.get('cipher', 'aes-256-cfb')
            obfs = node.get('obfs', 'plain')
            password_b64 = b64_encode(node.get('password', ''))
            
            main_part = f"{server}:{port}:{protocol}:{method}:{obfs}:{password_b64}"
            
            params = []
            if node.get('obfs-param'):
                params.append(f"obfsparam={b64_encode(node['obfs-param'])}")
            if node.get('protocol-param'):
                params.append(f"protoparam={b64_encode(node['protocol-param'])}")
            if node.get('name'):
                params.append(f"remarks={b64_encode(node['name'])}")
            if node.get('group'):
                params.append(f"group={b64_encode(node['group'])}")
            
            full_str = f"{main_part}/?{'&'.join(params)}"
            # 外部整体 SSR 链接也保持填充
            final_b64 = base64.b64encode(full_str.encode('utf-8')).decode('utf-8')
            return f"ssr://{final_b64}"
        except (TypeError, ValueError) as e:
            print(f"构建 SSR URL 失败: {e}")
            return None

    def build_url(self, node: Dict) -> Optional[str]:
        """
        按节点协议类型自动分派，构建对应格式的 URL。
        支持 ss / ssr / vmess / trojan / vless。
        """
        ntype = str(node.get('type', '')).lower()
        if ntype == 'ss':
            return self.build_ss_url(node)
        elif ntype == 'ssr':
            return self.build_ssr_url(node)
        elif ntype == 'vmess':
            return self.build_vmess_url(node)
        elif ntype == 'trojan':
            return self.build_trojan_url(node)
        elif ntype == 'vless':
            return self.build_vless_url(node)
        else:
            print(f"⚠️  跳过不支持导出的协议节点: {node.get('name', '?')} (type={ntype})")
            return None

    def to_txt(self, output_file: str) -> bool:
        """
        将节点导出为协议 URL txt 格式（支持 ss / ssr / vmess / trojan 混合导出）

        Args:
            output_file: 输出 txt 文件路径

        Returns:
            导出成功返回 True，失败返回 False
        """
        import os
        try:
            # 自动创建输出目录
            out_dir = os.path.dirname(os.path.abspath(output_file))
            os.makedirs(out_dir, exist_ok=True)

            exported, skipped = 0, 0
            with open(output_file, 'w', encoding='utf-8') as f:
                # 写入 REMARKS 和 STATUS 行
                if self.remarks or self.status:
                    line = f"REMARKS={self.remarks}"
                    if self.status:
                        line += f" STATUS={self.status}"
                    f.write(line + '\n')

                # 按协议分派写入每个节点的 URL
                for node in self.nodes:
                    url = self.build_url(node)
                    if url:
                        f.write(url + '\n')
                        exported += 1
                    else:
                        skipped += 1

            skip_msg = f"，跳过 {skipped} 个不支持的节点" if skipped else ''
            print(f"成功导出到 txt 文件: {output_file}（共 {exported} 个节点{skip_msg}）")
            return exported > 0

        except OSError as e:
            print(f"导出 txt 文件失败(文件系统错误): {e}")
            return False

    def to_v2rayn_base64(self, output_file: str) -> bool:
        """
        将节点导出为 v2rayN 兼容的 Base64 订阅格式
        """
        import os
        import base64
        try:
            out_dir = os.path.dirname(os.path.abspath(output_file))
            os.makedirs(out_dir, exist_ok=True)

            urls = []
            for node in self.nodes:
                url = self.build_url(node)
                if url:
                    urls.append(url)
            
            if not urls:
                print("⚠️  没有可导出的有效节点")
                return False
                
            content = "\n".join(urls)
            b64_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(b64_content)
                
            print(f"✅ 成功导出 v2rayN 订阅格式: {output_file} ({len(urls)} 个节点)")
            return True
        except OSError as e:
            print(f"导出 v2rayN 格式失败(文件系统错误): {e}")
            return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='SS协议节点转换工具 - 支持txt和yaml格式的双向转换',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # txt转yaml
  python ss_converter.py -i nodes.txt -o nodes.yaml
  
  # yaml转txt
  python ss_converter.py -i nodes.yaml -o nodes.txt
  
  # 自动检测格式
  python ss_converter.py -i input.txt -o output.yaml
        """
    )
    
    parser.add_argument('-i', '--input', required=True, 
                       help='输入文件路径')
    parser.add_argument('-o', '--output', required=True,
                       help='输出文件路径')
    parser.add_argument('-f', '--format', choices=['txt', 'yaml'],
                       help='指定输入文件格式(可选,默认自动检测)')
    
    args = parser.parse_args()
    
    # 创建转换器实例
    converter = SSNodeConverter()
    
    # 检测输入文件格式
    input_format = args.format
    if not input_format:
        if args.input.endswith('.yaml') or args.input.endswith('.yml'):
            input_format = 'yaml'
        else:
            input_format = 'txt'
    
    print(f"输入文件格式: {input_format}")
    
    # 解析输入文件
    if input_format == 'txt':
        if not converter.parse_txt_file(args.input):
            print("解析txt文件失败")
            sys.exit(1)
    else:
        if not converter.parse_yaml_file(args.input):
            print("解析yaml文件失败")
            sys.exit(1)
    
    # 检测输出文件格式
    if args.output.endswith('.yaml') or args.output.endswith('.yml'):
        output_format = 'yaml'
    else:
        output_format = 'txt'
    
    print(f"输出文件格式: {output_format}")
    
    # 导出到目标格式
    if output_format == 'yaml':
        if not converter.to_yaml(args.output):
            print("导出yaml文件失败")
            sys.exit(1)
    else:
        if not converter.to_txt(args.output):
            print("导出txt文件失败")
            sys.exit(1)
    
    print("转换完成!")


if __name__ == '__main__':
    main()

