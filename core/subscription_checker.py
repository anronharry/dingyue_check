#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅工具函数模块
提供被 node_tester.py / huyun_converter.py 等模块共用的工具函数：
  - PROXY_SCHEMES      : 支持的代理协议头常量元组
  - try_decode_b64     : 尝试 base64 解码订阅内容
  - build_http_session : 构建带自动重试的 HTTP Session（统一入口）
  - parse_node_line    : 按协议分派解析单行代理 URL
"""

import base64
from typing import Optional
import binascii


# 支持的代理协议头（所有模块共用）
PROXY_SCHEMES = ('vmess://', 'vless://', 'trojan://', 'ss://', 'ssr://',
                 'hysteria://', 'hysteria2://', 'tuic://')


import math
import re

def shannon_entropy(data: str) -> float:
    """计算文本数据的香农信息熵"""
    if not data:
        return 0
    entropy = 0
    for x in set(data):
        p_x = float(data.count(x)) / len(data)
        if p_x > 0:
            entropy += - p_x * math.log(p_x, 2)
    return entropy

def is_pseudo_200_response(content: str, headers: dict) -> bool:
    """特征库级：联合拦截流氓拦截页面的伪 200 问题"""
    content_lower = content.lower()
    
    # 策略 1: HTTP Header 指纹，若服务商并非 nginx/cloudflare 极大概率是中转报错页
    content_type = headers.get('Content-Type', '')
    if 'text/html' in content_type:
        return True

    # 策略 2: 页面特征词
    if re.search(r"<(html|head|body|script|style)", content_lower):
        return True
        
    # 策略 3: 信息熵校验。标准 Base64 编码的订阅节点通常具备很高的熵值 (> 4.8)
    # 而普通报错提醒字符串的熵值往往偏低 (< 4.0)
    if len(content) > 100 and shannon_entropy(content) < 4.0:
        return True

    return False

def try_decode_b64(text: str) -> str:
    """
    尝试对字符串进行 base64 解码。
    若解码后包含已知代理协议头则返回解码后内容，否则返回原字符串。
    """
    try:
        padding = 4 - len(text) % 4
        padded  = text + '=' * padding if padding != 4 else text
        decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
        if any(s in decoded for s in PROXY_SCHEMES):
            return decoded
    except (binascii.Error, UnicodeDecodeError):
        pass
    return text


def parse_node_line(line: str, converter) -> Optional[dict]:
    """
    解析单行代理协议 URL，按协议头分派到 SSNodeConverter 对应解析方法。

    支持协议：ss / vmess / trojan / vless
    （hysteria / tuic / ssr 由 Mihomo 配置层支持，此处不解析，返回 None）

    Args:
        line      : 已 strip() 的协议 URL 字符串
        converter : SSNodeConverter 实例

    Returns:
        Clash 格式节点字典，解析失败统一返回 None（静默）
    """
    if line.startswith('ssr://'):
        return converter.parse_ssr_url(line)
    if line.startswith('vmess://'):
        return converter.parse_vmess_url(line)
    if line.startswith('ss://'):
        return converter.parse_ss_url(line)
    if line.startswith('trojan://'):
        return converter.parse_trojan_url(line)
    if line.startswith('vless://'):
        return converter.parse_vless_url(line)
    return None


from __future__ import annotations
