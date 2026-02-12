"""
测试新的信息展示格式
"""
from utils import format_subscription_info, get_country_flag, format_remaining_time
from datetime import datetime, timedelta

# 模拟当前时间后的过期时间
expire_time = (datetime.now() + timedelta(days=9755, hours=4, minutes=27, seconds=14)).strftime("%Y-%m-%d %H:%M:%S")

# 模拟订阅数据
info = {
    'name': '【69云】- IPLC专线',
    'node_count': 70,
    'total': 152.11 * 1024**3,
    'used': 20.03 * 1024**3,
    'remaining': 132.08 * 1024**3,
    'usage_percent': 13.2,
    'expire_time': expire_time,
    'node_stats': {
        'countries': {
            '香港': 11, 
            '美国': 6, 
            '台湾': 4,
            '新加坡': 3,
            '英国': 2,
            '日本': 2
        },
        'protocols': {'SS': 66, 'VMess': 2}
    }
}

print("=" * 60)
print(format_subscription_info(info))
print("=" * 60)
