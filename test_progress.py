from utils import format_subscription_info

# 模拟订阅数据
info = {
    'name': '测试机场',
    'node_count': 10,
    'total': 152.11 * 1024**3,
    'used': 20.03 * 1024**3,
    'remaining': 132.08 * 1024**3,
    'usage_percent': 13.2,
    'expire_time': '2052-10-28 08:52:41',
    'node_stats': {
        'countries': {'香港': 5, '美国': 3, '日本': 2},
        'protocols': {'SS': 8, 'VMess': 2}
    }
}

print("=" * 60)
print(format_subscription_info(info))
print("=" * 60)
