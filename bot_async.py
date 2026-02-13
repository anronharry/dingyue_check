"""
Telegram 机场订阅解析机器人 - 异步版本
支持交互式按钮、订阅分组、导出导入等高级功能
内存优化版本，适合小内存 VPS
"""

import os
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

from parser import SubscriptionParser
from storage_enhanced import SubscriptionStorage
from utils import is_valid_url, format_subscription_info, format_traffic

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

# 初始化（延迟加载，节省内存）
parser = None
storage = None


def get_parser():
    """懒加载解析器"""
    global parser
    if parser is None:
        parser = SubscriptionParser(proxy_port=PROXY_PORT, use_proxy=False)
    return parser


def get_storage():
    """懒加载存储"""
    global storage
    if storage is None:
        storage = SubscriptionStorage()
    return storage


# ==================== 命令处理器 ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    welcome_message = """
👋 <b>欢迎使用机场订阅解析机器人！</b>

🔍 <b>功能说明:</b>
• 解析订阅链接，提取流量和节点信息
• 支持订阅分组管理（标签）
• 批量检测和导出导入
• 交互式按钮操作

🛠️ <b>常用命令:</b>
/check - 检测所有订阅
/list - 查看订阅列表（按标签分组）
/export - 导出所有订阅
/stats - 查看统计信息
/help - 查看帮助

🚀 <b>直接发送订阅链接即可开始！</b>
"""
    await update.message.reply_text(welcome_message, parse_mode='HTML')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /help 命令"""
    help_message = """
📖 <b>使用帮助</b>

<b>1️⃣ 添加订阅</b>
直接发送订阅链接（支持批量，每行一个）

<b>2️⃣ 管理订阅</b>
• 点击订阅结果下方的按钮进行操作
• 🔄 重新检测 - 刷新订阅信息
• 🏷️ 添加标签 - 为订阅分组
• 🗑️ 删除订阅 - 移除订阅

<b>3️⃣ 批量操作</b>
/check - 检测所有订阅
/check [标签] - 检测指定标签的订阅
/list - 查看所有订阅（按标签分组）

<b>4️⃣ 导出导入</b>
/export - 导出所有订阅为 JSON 文件
/import - 回复导出的文件进行导入

<b>5️⃣ 统计信息</b>
/stats - 查看订阅统计（总数、流量等）
"""
    await update.message.reply_text(help_message, parse_mode='HTML')


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /check 命令（支持按标签检测）"""
    store = get_storage()
    
    # 检查是否指定了标签
    tag = context.args[0] if context.args else None
    
    if tag:
        subscriptions = store.get_by_tag(tag)
        if not subscriptions:
            await update.message.reply_text(f"📭 标签 '{tag}' 下没有订阅")
            return
        msg_text = f"🔍 检测标签 '{tag}' 下的订阅 (共 {len(subscriptions)} 个)..."
    else:
        subscriptions = store.get_all()
        if not subscriptions:
            await update.message.reply_text("📭 暂无历史订阅记录")
            return
        msg_text = f"🔍 检测所有订阅 (共 {len(subscriptions)} 个)..."
    
    progress_msg = await update.message.reply_text(msg_text)
    
    # 异步并发检测（限制并发数，避免内存溢出）
    results = []
    semaphore = asyncio.Semaphore(3)  # 最多同时3个请求
    
    async def check_one(url, data):
        async with semaphore:
            try:
                # 在线程池中执行同步解析（避免阻塞）
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, get_parser().parse, url)
                
                # 更新存储
                store.add_or_update(url, result)
                
                return {
                    'name': result.get('name', '未知'),
                    'remaining': result.get('remaining', 0),
                    'expire_time': result.get('expire_time'),
                    'status': 'success'
                }
            except Exception as e:
                logger.error(f"检测失败 {url}: {e}")
                return {
                    'name': data.get('name', '未知'),
                    'status': 'failed',
                    'error': str(e)
                }
    
    # 并发检测
    tasks = [check_one(url, data) for url, data in subscriptions.items()]
    results = await asyncio.gather(*tasks)
    
    # 删除进度消息
    await progress_msg.delete()
    
    # 生成报告
    report = f"<b>📊 订阅检测报告</b>\n\n"
    report += f"总计: {len(results)} | 成功: {sum(1 for r in results if r['status'] == 'success')}\n"
    report += "—" * 20 + "\n\n"
    
    success_results = [r for r in results if r['status'] == 'success']
    if success_results:
        report += "<b>✅ 可用订阅:</b>\n\n"
        for item in success_results:
            remaining = format_traffic(item['remaining'])
            report += f"<b>{item['name']}</b>\n"
            report += f"剩余: {remaining}\n"
            if item.get('expire_time'):
                report += f"到期: {item['expire_time']}\n"
            report += "\n"
    
    await update.message.reply_text(report, parse_mode='HTML')


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /list 命令（按标签分组显示）"""
    store = get_storage()
    subscriptions = store.get_all()
    
    if not subscriptions:
        await update.message.reply_text("📭 暂无订阅")
        return
    
    # 按标签分组
    tags = store.get_all_tags()
    untagged = {url: data for url, data in subscriptions.items() if not data.get('tags')}
    
    message = f"<b>📋 订阅列表 (共 {len(subscriptions)} 个)</b>\n\n"
    
    # 显示有标签的订阅
    for tag in tags:
        tagged_subs = store.get_by_tag(tag)
        if tagged_subs:
            message += f"<b>🏷️ {tag} ({len(tagged_subs)})</b>\n"
            for url, data in tagged_subs.items():
                message += f"  • {data['name']}\n"
            message += "\n"
    
    # 显示无标签的订阅
    if untagged:
        message += f"<b>📦 未分组 ({len(untagged)})</b>\n"
        for url, data in untagged.items():
            message += f"  • {data['name']}\n"
    
    await update.message.reply_text(message, parse_mode='HTML')


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /stats 命令（统计信息）"""
    store = get_storage()
    stats = store.get_statistics()
    
    message = "<b>📊 订阅统计</b>\n\n"
    message += f"<b>订阅总数:</b> {stats['total']}\n"
    message += f"<b>有效订阅:</b> {stats['active']}\n"
    message += f"<b>已过期:</b> {stats['expired']}\n\n"
    message += f"<b>总流量:</b> {format_traffic(stats['total_traffic'])}\n"
    message += f"<b>剩余流量:</b> {format_traffic(stats['total_remaining'])}\n\n"
    
    if stats['tags']:
        message += f"<b>标签:</b> {', '.join(stats['tags'])}\n"
    
    await update.message.reply_text(message, parse_mode='HTML')


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /export 命令"""
    store = get_storage()
    
    # 导出到临时文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_file = f"data/export_{timestamp}.json"
    
    if store.export_to_file(export_file):
        # 发送文件
        with open(export_file, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"subscriptions_{timestamp}.json",
                caption=f"✅ 已导出 {len(store.get_all())} 个订阅"
            )
        
        # 删除临时文件
        os.remove(export_file)
    else:
        await update.message.reply_text("❌ 导出失败")


async def handle_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理订阅链接"""
    text = update.message.text.strip()
    urls = [line.strip() for line in text.split('\n') if line.strip()]
    
    for url in urls:
        if not is_valid_url(url):
            await update.message.reply_text(f"❌ 无效的 URL: {url[:50]}...")
            continue
        
        processing_msg = await update.message.reply_text(f"⏳ 正在解析...")
        
        try:
            # 异步解析
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, get_parser().parse, url)
            
            # 保存
            get_storage().add_or_update(url, result)
            
            # 格式化消息
            message = format_subscription_info(result, url)
            
            # 创建交互式按钮
            keyboard = [
                [
                    InlineKeyboardButton("🔄 重新检测", callback_data=f"recheck:{url}"),
                    InlineKeyboardButton("🗑️ 删除", callback_data=f"delete:{url}")
                ],
                [
                    InlineKeyboardButton("🏷️ 添加标签", callback_data=f"tag:{url}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await processing_msg.delete()
            await update.message.reply_text(
                message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            await processing_msg.delete()
            await update.message.reply_text(f"❌ 解析失败: {str(e)}")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    action, url = data.split(':', 1)
    
    store = get_storage()
    
    if action == 'recheck':
        # 重新检测
        await query.edit_message_text("⏳ 正在重新检测...")
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, get_parser().parse, url)
            store.add_or_update(url, result)
            
            message = format_subscription_info(result, url)
            keyboard = [
                [
                    InlineKeyboardButton("🔄 重新检测", callback_data=f"recheck:{url}"),
                    InlineKeyboardButton("🗑️ 删除", callback_data=f"delete:{url}")
                ],
                [
                    InlineKeyboardButton("🏷️ 添加标签", callback_data=f"tag:{url}")
                ]
            ]
            await query.edit_message_text(
                message,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await query.edit_message_text(f"❌ 检测失败: {str(e)}")
    
    elif action == 'delete':
        # 删除订阅
        if store.remove(url):
            await query.edit_message_text("✅ 已删除订阅")
        else:
            await query.edit_message_text("❌ 删除失败")
    
    elif action == 'tag':
        # 添加标签（请求用户输入）
        await query.edit_message_text(
            "请回复此消息并输入标签名（如：主力、备用）\n"
            f"订阅: {store.get_all().get(url, {}).get('name', 'Unknown')}"
        )
        # 保存上下文
        context.user_data['pending_tag_url'] = url


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理普通消息（可能是标签输入）"""
    # 检查是否是回复标签请求的消息
    if 'pending_tag_url' in context.user_data:
        url = context.user_data['pending_tag_url']
        tag = update.message.text.strip()
        
        store = get_storage()
        if store.add_tag(url, tag):
            await update.message.reply_text(f"✅ 已添加标签: {tag}")
        else:
            await update.message.reply_text(f"❌ 添加标签失败")
        
        del context.user_data['pending_tag_url']
    else:
        # 否则当作订阅链接处理
        await handle_subscription(update, context)


def main():
    """主函数"""
    if not BOT_TOKEN:
        logger.error("错误: 未设置 TELEGRAM_BOT_TOKEN")
        return
    
    logger.info("=" * 60)
    logger.info("正在启动机器人（异步版本）...")
    logger.info("支持: 交互式按钮、订阅分组、导出导入")
    logger.info("=" * 60)
    
    # 创建应用
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 注册处理器
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # 启动机器人
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
