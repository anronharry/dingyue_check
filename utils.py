"""
工具函数模块
提供流量转换、URL 验证等辅助功能
"""

import re
from urllib.parse import urlparse


def bytes_to_gb(bytes_value):
    """
    将字节转换为 GB
    
    Args:
        bytes_value: 字节数
        
    Returns:
        float: GB 数值
    """
    if bytes_value is None:
        return 0
    return bytes_value / (1024 ** 3)


def format_traffic(bytes_value):
    """
    格式化流量显示
    
    Args:
        bytes_value: 字节数
        
    Returns:
        str: 格式化后的流量字符串（如 "10.5 GB"）
    """
    if bytes_value is None or bytes_value == 0:
        return "0 B"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    size = float(bytes_value)
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    return f"{size:.2f} {units[unit_index]}"


def is_valid_url(url):
    """
    验证 URL 是否有效
    
    Args:
        url: 待验证的 URL
        
    Returns:
        bool: URL 是否有效
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def create_progress_bar(percent, length=10):
    """
    生成进度条字符串
    
    Args:
        percent: 百分比 (0-100)
        length: 进度条长度
        
    Returns:
        str: 进度条字符串，如 "[■■□□□□□□□□]"
    """
    if percent < 0:
        percent = 0
    elif percent > 100:
        percent = 100
        
    filled_length = int(length * percent / 100)
    # 确保至少显示一个块（如果 > 0）或不显示（如果 0）
    if percent > 0 and filled_length == 0:
        filled_length = 1
        
    bar = "■" * filled_length + "□" * (length - filled_length)
    return f"[{bar}]"


def get_country_flag(country_name):
    """
    获取国家/地区对应的国旗 Emoji
    """
    flags = {
        '香港': '🇭🇰', '台湾': '🇹🇼', '日本': '🇯🇵', '美国': '🇺🇸',
        '新加坡': '🇸🇬', '韩国': '🇰🇷', '英国': '🇬🇧', '德国': '🇩🇪',
        '法国': '🇫🇷', '加拿大': '🇨🇦', '澳大利亚': '🇦🇺', '俄罗斯': '🇷🇺',
        '印度': '🇮🇳', '荷兰': '🇳🇱', '土耳其': '🇹🇷', '巴西': '🇧🇷',
        '越南': '🇻🇳', '泰国': '🇹🇭', '菲律宾': '🇵🇭', '马来西亚': '🇲🇾',
        '印尼': '🇮🇩', '阿根廷': '🇦🇷', '墨西哥': '🇲🇽', '其他': '🌐'
    }
    return flags.get(country_name, '🏳️')


def format_remaining_time(expire_time_str):
    """
    计算剩余时间
    """
    try:
        from datetime import datetime
        expire_date = datetime.strptime(expire_time_str, '%Y-%m-%d %H:%M:%S')
        now = datetime.now()
        
        if expire_date < now:
            return "已过期"
            
        delta = expire_date - now
        days = delta.days
        seconds = delta.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        sec = seconds % 60
        
        return f"{days}天{hours}时{minutes}分{sec}秒"
    except:
        return ""


import html

def format_subscription_info(info, url=None):
    """
    格式化订阅信息为友好的消息文本
    """
    message = "<b>🚀 订阅及节点信息统计</b>\n\n"
    
    # 机场名称
    if info.get('name'):
        name = html.escape(info['name'])
        message += f"<b>配置名称:</b> {name}\n"
    
    # 流量信息 (模仿截图风格)
    if any(key in info for key in ['total', 'used', 'remaining']):
        used = format_traffic(info.get('used', 0))
        total = format_traffic(info.get('total', 0))
        remaining = format_traffic(info.get('remaining', 0))
        
        message += f"<b>流量详情:</b> {used} / {total}\n"
        
        if info.get('usage_percent') is not None:
            percent = info['usage_percent']
            bar = create_progress_bar(percent, length=10)
            message += f"<b>使用进度:</b> {bar} {percent:.1f}%\n"
            
        if info.get('remaining') is not None:
            message += f"<b>剩余可用:</b> {remaining}\n"
            
    else:
        message += "<b>流量信息:</b> 无\n"
    
    # 到期时间 & 剩余时间
    if info.get('expire_time'):
        message += f"<b>过期时间:</b> {info['expire_time']}\n"
        remaining_time = format_remaining_time(info['expire_time'])
        if remaining_time:
            message += f"<b>剩余时间:</b> {remaining_time}\n"
            
    message += "\n" + "—" * 20 + "\n\n"

    # 节点统计信息
    if info.get('node_stats'):
        stats = info['node_stats']
        
        # 国家/地区分布 (带国旗)
        if stats.get('countries'):
            message += "<b>🌍 节点区域分布:</b>\n"
            countries = stats['countries']
            # 按数量排序
            sorted_countries = sorted(countries.items(), key=lambda x: x[1], reverse=True)
            for country, count in sorted_countries:
                flag = get_country_flag(country)
                country_escaped = html.escape(country)
                message += f"{flag} {country_escaped}: {count}\n"
            message += "\n"
        
        # 协议分布
        if stats.get('protocols'):
            message += "<b>🔐 协议分布:</b>\n"
            protocols = stats['protocols']
            sorted_protocols = sorted(protocols.items(), key=lambda x: x[1], reverse=True)
            for protocol, count in sorted_protocols:
                message += f"{protocol.upper()}: {count}\n"
                
    # 节点数量摘要
    if info.get('node_count') is not None:
         message += f"\n<b>📍 节点总数:</b> {info['node_count']}\n"
    
    # 添加原始链接（点击复制）
    if url:
        message += f"\n<b>📋 原始链接 (点击复制):</b>\n<code>{url}</code>"
         
    return message

