"""
Telegram 机场订阅解析机器人
手动轮询版本 - 绕过 Windows asyncio 问题
"""

import os
import time
import logging
from dotenv import load_dotenv
import requests

from parser import SubscriptionParser
from utils import is_valid_url, format_subscription_info

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 获取配置
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
PROXY_PORT = int(os.getenv('PROXY_PORT', 7890))

from storage import SubscriptionStorage
from datetime import datetime

# 初始化解析器（不使用代理）
parser = SubscriptionParser(proxy_port=PROXY_PORT, use_proxy=False)

# 初始化存储
storage = SubscriptionStorage()

# Telegram API 基础 URL
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_message(chat_id, text):
    """发送消息"""
    try:
        url = f"{API_BASE}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, json=data, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"发送消息失败: {e}")
        return None


def delete_message(chat_id, message_id):
    """删除消息"""
    try:
        url = f"{API_BASE}/deleteMessage"
        data = {
            'chat_id': chat_id,
            'message_id': message_id
        }
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        logger.error(f"删除消息失败: {e}")


def get_updates(offset=None):
    """获取更新"""
    try:
        url = f"{API_BASE}/getUpdates"
        params = {
            'timeout': 30,
            'offset': offset
        }
        response = requests.get(url, params=params, timeout=35)
        return response.json()
    except Exception as e:
        logger.error(f"获取更新失败: {e}")
        return {'ok': False}


def handle_start(chat_id):
    """处理 /start 命令"""
    welcome_message = """
👋 欢迎使用机场订阅解析机器人！

🔍 功能说明:
本机器人可以帮你解析机场订阅链接，提取以下信息：
• 机场名称
• 节点数量
• 流量使用情况
• 到期时间（如果有）

🛠️ 常用命令:
/check - 一键检测所有历史订阅（智能跳过已过期）

🚀 直接发送订阅链接即可开始（支持批量发送）！
"""
    send_message(chat_id, welcome_message)


def handle_help(chat_id):
    """处理 /help 命令"""
    help_message = """
📖 使用帮助

1️⃣ 直接发送订阅链接
   - 支持单个链接
   - 支持批量链接（每行一个）
   - 解析成功会自动保存到历史记录

2️⃣ 使用 /check 命令
   - 检测所有历史订阅
   - 自动跳过已过期的订阅
   - 重新检测未过期的订阅并输出报表

3️⃣ 隐私说明
   - 所有数据仅保存在本地
   - 不会上传到任何第三方服务器
"""
    send_message(chat_id, help_message)


def handle_check_all(chat_id):
    """处理 /check 命令（批量检测）"""
    subscriptions = storage.get_all()
    
    if not subscriptions:
        send_message(chat_id, "📭 暂无历史订阅记录，请先发送订阅链接。")
        return

    msg = send_message(chat_id, f"🔍 开始检测历史订阅 (共 {len(subscriptions)} 个)...\n智能跳过已过期，只检测有效订阅。")
    
    valid_results = []
    expired_count = 0
    checked_count = 0
    
    now = datetime.now()
    
    for url, data in subscriptions.items():
        # 1. 检查是否过期
        expire_time_str = data.get('expire_time')
        if expire_time_str:
            try:
                expire_date = datetime.strptime(expire_time_str, '%Y-%m-%d %H:%M:%S')
                if expire_date < now:
                    expired_count += 1
                    logger.info(f"跳过已过期订阅: {data.get('name')}")
                    continue
            except:
                pass # 解析时间出错，默认重新检测
        
        # 2. 重新检测未过期的
        try:
            checked_count += 1
            # send_message(chat_id, f"正在检测: {data.get('name', '未知')}...")
            result = parser.parse(url)
            
            # 更新存储
            storage.add_or_update(url, result)
            
            # 添加到有效列表
            valid_results.append({
                'name': result.get('name', '未知订阅'),
                'remaining': result.get('remaining', 0),
                'url': url
            })
            
        except Exception as e:
            logger.error(f"检测失败 {url}: {e}")
            # 如果检测失败，可能链接失效了，可以选择暂不删除或标记错误
            
    # 删除进度提示
    if msg:
        delete_message(chat_id, msg['result']['message_id'])
        
    # 生成汇总报告
    report = f"<b>📊 历史订阅检测报告</b>\n\n"
    report += f"总计: {len(subscriptions)} | 已过期(跳过): {expired_count} | 实测: {checked_count}\n"
    report += "—" * 20 + "\n\n"
    
    if valid_results:
        report += "<b>✅ 可用订阅列表:</b>\n\n"
        for item in valid_results:
            from utils import format_traffic
            remaining = format_traffic(item['remaining'])
            report += f"<b>{item['name']}</b>\n"
            report += f"剩余流量: {remaining}\n"
            report += f"<code>{item['url']}</code>\n\n"
    else:
        report += "❌ 没有发现可用的订阅链接。\n"
        
    send_message(chat_id, report)


def handle_subscription(chat_id, text):
    """处理订阅链接（支持多链接）"""
    # 按行分割，过滤空行
    urls = [line.strip() for line in text.split('\n') if line.strip()]
    
    if not urls:
        return

    for url in urls:
        # 验证 URL
        if not is_valid_url(url):
            send_message(
                chat_id,
                f"❌ 这不是一个有效的 URL: <code>{url}</code>\n\n"
                "请发送正确的订阅链接，例如:\n"
                "https://example.com/api/v1/client/subscribe?token=xxxxx"
            )
            continue
            
        # 发送"正在解析"提示
        processing_msg = send_message(chat_id, f"⏳ 正在解析: <code>{url[:50]}...</code>")
        processing_msg_id = processing_msg.get('result', {}).get('message_id') if processing_msg else None
        
        try:
            # 解析订阅
            logger.info(f"开始解析订阅: {url}")
            result = parser.parse(url)
            
            # 保存到存储
            storage.add_or_update(url, result)
            
            # 格式化输出
            message = format_subscription_info(result, url)
            
            # 删除"正在解析"提示
            if processing_msg_id:
                delete_message(chat_id, processing_msg_id)
            
            # 发送结果
            send_message(chat_id, message)
            
            logger.info(f"解析成功: {result.get('name', 'Unknown')}")
                
        except Exception as e:
            logger.error(f"解析失败: {e}")
            
            # 删除"正在解析"提示
            if processing_msg_id:
                delete_message(chat_id, processing_msg_id)
            
            # 发送错误消息
            error_str = str(e)
            if len(error_str) > 500:
                error_str = error_str[:500] + "..."
            error_message = f"❌ 解析失败 (<code>{url[:50]}...</code>)\n\n错误信息: {error_str}\n\n"
            error_message += "可能的原因:\n"
            error_message += "• 订阅链接无效或已过期\n"
            error_message += "• 网络连接问题\n"
            error_message += "• 代理服务未运行\n"
            error_message += "• 订阅格式不支持\n\n"
            error_message += "💡 请检查后重试"
            send_message(chat_id, error_message)


def process_update(update):
    """处理单个更新"""
    try:
        if 'message' not in update:
            return
        
        message = update['message']
        chat_id = message['chat']['id']
        
        # 处理文本消息
        if 'text' in message:
            text = message['text'].strip()
            
            # 处理命令
            if text.startswith('/start'):
                handle_start(chat_id)
            elif text.startswith('/help'):
                handle_help(chat_id)
            elif text.startswith('/check'):
                handle_check_all(chat_id)
            else:
                # 处理订阅链接
                handle_subscription(chat_id, text)
    
    except Exception as e:
        logger.error(f"处理更新失败: {e}")


def main():
    """主函数"""
    # 检查 Token
    if not BOT_TOKEN:
        logger.error("错误: 未设置 TELEGRAM_BOT_TOKEN")
        logger.error("请在 .env 文件中配置你的 Bot Token")
        return
    
    logger.info("=" * 60)
    logger.info("正在启动机器人（手动轮询模式）...")
    logger.info(f"代理端口: {PROXY_PORT}")
    logger.info("此版本绕过了 Windows asyncio 问题")
    logger.info("按 Ctrl+C 停止")
    logger.info("=" * 60)
    
    offset = None
    
    try:
        while True:
            # 获取更新
            result = get_updates(offset)
            
            if not result.get('ok'):
                logger.warning("获取更新失败，等待 5 秒后重试...")
                time.sleep(5)
                continue
            
            updates = result.get('result', [])
            
            # 处理每个更新
            for update in updates:
                process_update(update)
                offset = update['update_id'] + 1
            
            # 如果没有更新，短暂休眠
            if not updates:
                time.sleep(0.5)
    
    except KeyboardInterrupt:
        logger.info("\n机器人已停止")
    except Exception as e:
        logger.error(f"运行错误: {e}")
        raise


if __name__ == '__main__':
    main()
