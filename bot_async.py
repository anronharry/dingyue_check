"""
Telegram 机场订阅解析机器人 - 异步版本
支持交互式按钮、订阅分组、导出导入等高级功能
内存优化版本，适合小内存 VPS
"""

import os
import logging
import asyncio
import time
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
from input_detector import InputDetector
from file_handler import FileHandler

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

async def send_long_message(update: Update, text: str, **kwargs):
    """安全发送长消息，超过 3500 字按块切割，防止 Telegram API 报错"""
    MAX_LENGTH = 3500
    if len(text) <= MAX_LENGTH:
        await update.message.reply_text(text, **kwargs)
        return
        
    # 按行分割尽量保证不切断 HTML 标签
    lines = text.split('\n')
    current_chunk = ""
    
    for line in lines:
        if len(current_chunk) + len(line) + 1 > MAX_LENGTH:
            await update.message.reply_text(current_chunk, **kwargs)
            current_chunk = line + "\n"
            await asyncio.sleep(0.5)  # 防限流
        else:
            current_chunk += line + "\n"
            
    if current_chunk.strip():
        await update.message.reply_text(current_chunk, **kwargs)


# ==================== 命令处理器 ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    welcome_message = """
👋 <b>欢迎使用智能订阅检测机器人!</b>

🔍 <b>功能说明:</b>
• 🌍 真实IP地理位置查询(城市、ISP)
• 📊 智能识别订阅链接、文件、节点文本
• 📄 支持上传txt/yaml文件自动解析
• 🏷️ 订阅分组管理(标签)
• 📤 批量检测和导出导入

🛠️ <b>使用方式:</b>
• 直接发送订阅链接
• 上传txt/yaml文件
• 粘贴节点列表文本

📋 <b>常用命令:</b>
/check - 检测所有订阅
/list - 查看订阅列表
/stats - 查看统计信息
/help - 查看帮助

🚀 <b>现在就发送订阅链接或上传文件试试!</b>
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
    
    total_count = len(subscriptions)
    completed_count = 0
    last_update_time = time.time()
    
    async def check_one(url, data):
        nonlocal completed_count, last_update_time
        async with semaphore:
            try:
                # 在线程池中执行同步解析（避免阻塞）
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, get_parser().parse, url)
                
                # 更新存储
                store.add_or_update(url, result)
                
                res = {
                    'name': result.get('name', '未知'),
                    'remaining': result.get('remaining', 0),
                    'expire_time': result.get('expire_time'),
                    'status': 'success'
                }
            except Exception as e:
                logger.error(f"检测失败 {url}: {e}")
                res = {
                    'name': data.get('name', '未知'),
                    'status': 'failed',
                    'error': str(e)
                }
                
            # UX优化：动态更新进度条
            completed_count += 1
            current_time = time.time()
            if current_time - last_update_time > 2.0 or completed_count == total_count:
                try:
                    await progress_msg.edit_text(f"⏳ 正在检测: {completed_count} / {total_count} 完成...")
                    last_update_time = current_time
                except:
                    pass
            return res
    
    # 并发检测
    tasks = [check_one(url, data) for url, data in subscriptions.items()]
    results = await asyncio.gather(*tasks)
    
    # 删除进度消息
    try:
        await progress_msg.delete()
    except Exception as exc:
        logger.warning(f"删除进度消息失败: {exc}")
    
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
    
    await send_long_message(update, report, parse_mode='HTML')
    
    # 低内存优化：主动清理垃圾
    import gc
    gc.collect()


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
    
    await send_long_message(update, message, parse_mode='HTML')


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
    loop = asyncio.get_event_loop()
    
    # 在线程中执行导出，防止阻塞事件循环
    export_success = await loop.run_in_executor(None, store.export_to_file, export_file)
    
    if export_success:
        # 发送文件
        with open(export_file, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"subscriptions_{timestamp}.json",
                caption=f"✅ 已导出 {len(store.get_all())} 个订阅"
            )
        
        # 删除临时文件
        await loop.run_in_executor(None, os.remove, export_file)
    else:
        await update.message.reply_text("❌ 导出失败")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理文件上传(智能检测订阅链接)"""
    document = update.message.document
    file_type = InputDetector.detect_file_type(document.file_name)
    
    if file_type == 'unknown':
        await update.message.reply_text("❌ 不支持的文件类型,请上传txt或yaml文件")
        return
    
    processing_msg = await update.message.reply_text(f"📄 正在分析{file_type.upper()}文件...")
    
    try:
        # 下载文件
        file = await document.get_file()
        file_content = await file.download_as_bytearray()
        content_bytes = bytes(file_content)
        
        # 智能检测: 优先查找订阅链接
        if file_type == 'txt':
            subscription_urls = FileHandler.extract_subscription_urls(content_bytes)
            
            if subscription_urls:
                # 发现订阅链接 -> 解析订阅获取流量信息
                await processing_msg.edit_text(
                    f"🔗 发现 {len(subscription_urls)} 个订阅链接,正在解析...\n"
                    f"这可能需要一些时间,请稍候..."
                )
                
                results = []
                for idx, url in enumerate(subscription_urls, 1):
                    try:
                        # 异步解析订阅
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(None, get_parser().parse, url)
                        
                        # 保存到存储
                        get_storage().add_or_update(url, result)
                        
                        results.append({
                            'index': idx,
                            'url': url,
                            'data': result,
                            'status': 'success'
                        })
                    except Exception as e:
                        logger.error(f"订阅解析失败 {url}: {e}")
                        results.append({
                            'index': idx,
                            'url': url,
                            'error': str(e),
                            'status': 'failed'
                        })
                
                # 生成汇总报告
                try:
                    await processing_msg.delete()
                except Exception as exc:
                    logger.warning(f"删除进度消息失败: {exc}")
                
                # 发送每个订阅的详细信息
                for res in results:
                    if res['status'] == 'success':
                        data = res['data']
                        message = f"<b>📊 订阅 {res['index']}</b>\n\n"
                        message += format_subscription_info(data, res['url'])
                        
                        # 创建交互按钮
                        keyboard = [
                            [
                                InlineKeyboardButton("🔄 重新检测", callback_data=f"recheck:{res['url']}"),
                                InlineKeyboardButton("🗑️ 删除", callback_data=f"delete:{res['url']}")
                            ],
                            [
                                InlineKeyboardButton("🏷️ 添加标签", callback_data=f"tag:{res['url']}")
                            ]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await update.message.reply_text(message, parse_mode='HTML', reply_markup=reply_markup)
                    else:
                        await update.message.reply_text(
                            f"❌ <b>订阅 {res['index']}</b> 解析失败\n"
                            f"错误: {res['error']}",
                            parse_mode='HTML'
                        )
                
                # 发送汇总
                summary = f"<b>✅ 文件分析完成</b>\n\n"
                summary += f"总订阅数: {len(subscription_urls)}\n"
                summary += f"成功解析: {sum(1 for r in results if r['status'] == 'success')}\n"
                summary += f"解析失败: {sum(1 for r in results if r['status'] == 'failed')}"
                await update.message.reply_text(summary, parse_mode='HTML')
                
                return
        
        # 没有订阅链接 -> 解析节点列表
        if file_type == 'txt':
            nodes = FileHandler.parse_txt_file(content_bytes)
        elif file_type == 'yaml':
            nodes = FileHandler.parse_yaml_file(content_bytes)
        else:
            await processing_msg.edit_text("❌ 文件格式错误")
            return
        
        if not nodes:
            await processing_msg.edit_text(
                "❌ 未能从文件中解析出内容\n\n"
                "提示: 如果文件包含订阅链接,请确保链接格式正确(http/https开头)"
            )
            return
        
        # 分析节点
        parser_instance = get_parser()
        node_stats = parser_instance._analyze_nodes(nodes)
        
        # 构建结果 (低内存优化：剥离原始 nodes 数组)
        result = {
            'name': f"{document.file_name} (节点列表)",
            'node_count': len(nodes),
            'node_stats': node_stats
        }
        
        # 格式化消息
        message = "📝 <b>节点列表分析</b>\n\n"
        message += format_subscription_info(result)
        message += "\n\n<i>💡 提示: 节点列表无法显示流量信息,如需查看流量请发送订阅链接</i>"
        
        try:
            await processing_msg.delete()
        except Exception as exc:
            logger.warning(f"删除进度消息失败: {exc}")
        await update.message.reply_text(message, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"文件处理失败: {e}")
        error_msg = str(e)
        if len(error_msg) > 500:
            error_msg = error_msg[:500] + "..."
        try:
            await processing_msg.edit_text(f"❌ 文件处理失败: {error_msg}")
        except Exception:
            await update.message.reply_text(f"❌ 文件处理失败: {error_msg}")


async def handle_node_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理节点文本列表"""
    text = update.message.text.strip()
    
    processing_msg = await update.message.reply_text("📝 正在解析节点列表...")
    
    try:
        # 解析节点文本
        nodes = FileHandler.parse_txt_file(text.encode('utf-8'))
        
        if not nodes:
            await processing_msg.edit_text("❌ 未能解析出有效节点")
            return
        
        # 分析节点
        parser_instance = get_parser()
        node_stats = parser_instance._analyze_nodes(nodes)
        
        # 构建结果 (低内存优化：剥离原始 nodes 数组)
        result = {
            'name': '节点列表',
            'node_count': len(nodes),
            'node_stats': node_stats
        }
        
        # 格式化消息
        message = format_subscription_info(result)
        
        try:
            await processing_msg.delete()
        except Exception as exc:
            logger.warning(f"删除进度消息失败: {exc}")
        await update.message.reply_text(message, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"节点文本解析失败: {e}")
        error_msg = str(e)
        if len(error_msg) > 500:
            error_msg = error_msg[:500] + "..."
        try:
            await processing_msg.edit_text(f"❌ 解析失败: {error_msg}")
        except Exception:
            await update.message.reply_text(f"❌ 解析失败: {error_msg}")


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
            
            try:
                await processing_msg.delete()
            except Exception as exc:
                logger.warning(f"删除进度消息失败: {exc}")
            await update.message.reply_text(
                message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            error_msg = str(e)
            if len(error_msg) > 500:
                error_msg = error_msg[:500] + "..."
            try:
                await processing_msg.edit_text(f"❌ 解析失败: {error_msg}")
            except Exception:
                await update.message.reply_text(f"❌ 解析失败: {error_msg}")


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
    """处理普通消息(智能识别输入类型)"""
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
        return
    
    # 智能检测输入类型
    input_type = InputDetector.detect_message_type(update)
    
    if input_type == 'file':
        await handle_document(update, context)
    elif input_type == 'url':
        await handle_subscription(update, context)
    elif input_type == 'node_text':
        await handle_node_text(update, context)
    else:
        await update.message.reply_text(
            "❌ 无法识别的输入类型\n\n"
            "请发送:\n"
            "• 订阅链接(http/https)\n"
            "• 上传txt/yaml文件\n"
            "• 粘贴节点列表(vmess://, ss://, 等)"
        )


def main():
    """主函数"""
    if not BOT_TOKEN:
        logger.error("错误: 未设置 TELEGRAM_BOT_TOKEN")
        return
    
    logger.info("=" * 60)
    logger.info("正在启动智能订阅检测机器人...")
    logger.info("支持: IP地理位置、文件处理、智能输入识别")
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
    
    # 文件处理器(优先级高)
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # 文本消息处理器
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # 启动机器人
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
