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

# 初始化解析器（不使用代理）
parser = SubscriptionParser(proxy_port=PROXY_PORT, use_proxy=False)

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

📝 使用方法:
直接发送你的订阅链接给我即可！

💡 示例:
https://example.com/api/v1/client/subscribe?token=xxxxx

❓ 需要帮助？发送 /help 查看详细说明
"""
    send_message(chat_id, welcome_message)


def handle_help(chat_id):
    """处理 /help 命令"""
    help_message = """
📖 使用帮助

🎯 主要功能:
解析机场订阅链接，获取详细信息

🔧 使用步骤:
1️⃣ 从你的机场获取订阅链接
2️⃣ 将链接发送给本机器人
3️⃣ 等待解析结果

⚠️ 注意事项:
• 请确保订阅链接有效且可访问
• 机器人通过本地代理访问订阅链接
• 解析过程可能需要几秒钟

🔒 隐私说明:
• 机器人不会保存你的订阅链接
• 所有数据仅用于临时解析
• 解析完成后立即清除

❓ 遇到问题？
• 检查订阅链接是否正确
• 确认订阅未过期
• 确保代理服务正常运行
"""
    send_message(chat_id, help_message)


def handle_subscription(chat_id, url):
    """处理订阅链接"""
    # 验证 URL
    if not is_valid_url(url):
        send_message(
            chat_id,
            "❌ 这不是一个有效的 URL\n\n"
            "请发送正确的订阅链接，例如:\n"
            "https://example.com/api/v1/client/subscribe?token=xxxxx"
        )
        return
    
    # 发送处理中提示
    processing_msg = send_message(chat_id, "⏳ 正在解析订阅链接，请稍候...")
    processing_msg_id = processing_msg.get('result', {}).get('message_id') if processing_msg else None
    
    try:
        # 解析订阅
        logger.info(f"开始解析订阅: {url}")
        subscription_info = parser.parse(url)
        
        # 格式化结果
        result_message = format_subscription_info(subscription_info)
        
        # 删除处理中消息
        if processing_msg_id:
            delete_message(chat_id, processing_msg_id)
        
        # 发送结果
        send_message(chat_id, result_message)
        
        logger.info(f"解析成功: {subscription_info.get('name', 'Unknown')}")
        
    except Exception as e:
        logger.error(f"解析失败: {str(e)}")
        
        # 删除处理中消息
        if processing_msg_id:
            delete_message(chat_id, processing_msg_id)
        
        # 发送错误消息
        error_message = f"❌ 解析失败\n\n错误信息: {str(e)}\n\n"
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
