"""
Telegram 机场订阅解析机器人 - 异步版本
支持交互式按钮、订阅分组、导出导入等高级功能
内存优化版本，适合小内存 VPS
"""

import os
import logging
import asyncio
import sys
import time
import hashlib
from collections import OrderedDict
from datetime import datetime
from dotenv import load_dotenv

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

from core.parser import SubscriptionParser
from core.storage_enhanced import SubscriptionStorage
from utils.utils import is_valid_url, format_subscription_info, format_traffic, InputDetector
from core.file_handler import FileHandler
from core.converters.ss_converter import SSNodeConverter
from core.workspace_manager import WorkspaceManager
from core.node_tester import _async_run_node_latency_test
from core.access_control import UserManager

# 导入高级体验模块
from features import latency_tester
from features import monitor

# 导入功能开关配置
import config

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
URL_CACHE_MAX_SIZE = int(os.getenv('URL_CACHE_MAX_SIZE', 5000))
URL_CACHE_TTL_SECONDS = int(os.getenv('URL_CACHE_TTL_SECONDS', 86400))

# 用户白名单：从环境变量读取允许的 Telegram User ID
# 格式：ALLOWED_USER_IDS=123456789,987654321（多个用英文逗号分隔）
_raw_ids = os.getenv('ALLOWED_USER_IDS', '').strip()
ALLOWED_USER_IDS = {
    int(uid) for uid in _raw_ids.split(',') if uid.strip().isdigit()
}
if not ALLOWED_USER_IDS:
    logger.info("ℹ️ ALLOWED_USER_IDS 静态白名单为空，目前仅允许 Owner 或通过 /adduser 动态添加的用户使用机器人。")
else:
    logger.info(f"✅ 用户白名单已部分启用，当前共有 {len(ALLOWED_USER_IDS)} 个 ENV 级静态授权用户")


# 初始化（延迟加载，节省内存）
parser = None
storage = None
ws_manager = WorkspaceManager("data")
user_manager = UserManager(os.path.join("data", "db", "users.json"), config.OWNER_ID)

# 短链接缓存池 (解决 Telegram <= 64 bytes 按钮数据限制)
# key: short hash, value: {'url': str, 'ts': float}
url_cache = OrderedDict()


def make_sub_keyboard(url: str) -> InlineKeyboardMarkup:
    """构建订阅操作内联键盘，按功能开关动态显示按钮"""
    row1 = [
        InlineKeyboardButton("🔄 重新检测", callback_data=get_short_callback_data("recheck", url)),
    ]
    # 测速按钮受功能开关控制
    if config.ENABLE_LATENCY_TESTER:
        row1.append(InlineKeyboardButton("⚡ 节点测速", callback_data=get_short_callback_data("ping", url)))
    row1.append(InlineKeyboardButton("🗑️ 删除", callback_data=get_short_callback_data("delete", url)))

    return InlineKeyboardMarkup([
        row1,
        [InlineKeyboardButton("🏷️ 添加标签", callback_data=get_short_callback_data("tag", url))]
    ])


def _cleanup_url_cache():
    """清理过期和超量缓存，防止长期运行内存增长。"""
    now = time.time()

    expired_keys = [
        key for key, value in url_cache.items()
        if now - value.get('ts', 0) > URL_CACHE_TTL_SECONDS
    ]
    for key in expired_keys:
        url_cache.pop(key, None)

    while len(url_cache) > URL_CACHE_MAX_SIZE:
        url_cache.popitem(last=False)

async def _periodic_url_cache_cleanup(context: ContextTypes.DEFAULT_TYPE):
    """供 JobQueue 调用的后台定期清理任务，避免阻塞主循环。"""
    _cleanup_url_cache()

def get_short_callback_data(action, url):
    """计算短 hash 突破回调长度限制"""
    # [性能优化] 取消了此处的同步 _cleanup_url_cache 调用，由后台异步 Task 统一处理
    hash_key = hashlib.md5(url.encode('utf-8')).hexdigest()[:16]
    url_cache[hash_key] = {'url': url, 'ts': time.time()}
    url_cache.move_to_end(hash_key)
    return f"{action}:{hash_key}"
# 全局解析器与共享 Session (Expert Optimization)
shared_session = None

async def get_parser():
    """具备 Session 复用能力的解析器获取器"""
    global parser, shared_session
    if shared_session is None:
        import aiohttp
        # 预设较大的连接池以支持 1GB 服务器的高并发
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=20)
        shared_session = aiohttp.ClientSession(connector=connector)
        
    if parser is None:
        parser = SubscriptionParser(proxy_port=PROXY_PORT, use_proxy=False, session=shared_session)
    return parser

async def _on_shutdown(application: Application):
    """优雅关闭全局异步会话池"""
    logger.info("正在关闭全局 HTTP Session 池...")
    global parser, shared_session
    if parser and hasattr(parser, 'session') and parser.session:
        await parser.session.close()
        logger.info("SubscriptionParser 的 HTTP Session 已关闭。")
    elif shared_session:
        await shared_session.close()
        logger.info("共享 HTTP Session 已关闭。")
    
    # 获取单实例清理
    from core.geo_service import GeoLocationService
    geo_client = GeoLocationService()
    if hasattr(geo_client, 'close'):
        await geo_client.close()
        logger.info("GeoLocationService 的 HTTP Session 已关闭。")
    logger.info("后台 HTTP Session 池清理完毕。")


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


def is_authorized(update: Update) -> bool:
    """检查用户是否授权 (Fail-Safe 安全增强版)"""
    user = update.effective_user
    if user is None: 
        return False
        
    uid = user.id
    
    # 规则 1: Owner 总是拥有最高访问权限
    if user_manager.is_owner(uid):
        return True
        
    # 规则 2: 优先检查通过 /adduser 动态添加到数据库的用户池，以及环境变量设置的静态名单
    return user_manager.is_authorized(uid) or uid in ALLOWED_USER_IDS

def is_owner(update: Update) -> bool:
    """检查是否为 Owner"""
    user = update.effective_user
    if user is None: 
        return False
    return user_manager.is_owner(user.id)


async def _send_no_permission_msg(update: Update):
    """向无权限用户统一发送拒绝提示（含联系方式）"""
    msg = (
        "⛔ <b>您无权使用此机器人。</b>\n\n"
        "如需获得使用权限，请私信联系：\n"
        "👉 <a href=\"https://t.me/qinhuaichuanbot\">@qinhuaichuanbot</a>"
    )
    try:
        if update.message:
            await update.message.reply_text(msg, parse_mode='HTML')
        elif update.callback_query:
            await update.callback_query.answer("⛔ 无权限，请联系 @qinhuaichuanbot", show_alert=True)
    except Exception as e:
        logger.warning(f"发送权限拒绝提示失败: {e}")


# ==================== 命令处理器 ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    if not is_authorized(update):
        logger.warning(f"未授权访问 /start，用户 ID: {update.effective_user.id}")
        return
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
/delete - 删除订阅
/stats - 查看统计信息
/help - 查看帮助

🚀 <b>现在就发送订阅链接或上传文件试试!</b>
"""
    await update.message.reply_text(welcome_message, parse_mode='HTML')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /help 命令"""
    if not is_authorized(update):
        await _send_no_permission_msg(update)
        return
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
/check - 检测您的所有订阅
/check [标签] - 检测指定标签的订阅
/list - 查看您的订阅（按标签分组，可直接操作）

<b>4️⃣ 删除订阅</b>
/delete - 显示删除帮助
/delete &lt;订阅链接&gt; - 直接删除指定订阅

<b>5️⃣ 统计与全局巡检</b>
/stats - 查看您的订阅统计（总数、流量等）
/checkall - [仅 Owner] 检测所有用户的订阅

<b>6️⃣ 格式转换 (回复文件有效)</b>
/to_yaml - 将 txt 节点列表转换为 Clash YAML
/to_txt - 将 yaml 配置文件转换为明文 TXT 列表

<b>7️⃣ 高级检测 (Mihomo 内核)</b>
/deepcheck - [实验性] 真实外网连通性测活 (回复文件有效)

<b>8️⃣ Owner 管理功能</b>
/adduser /deluser /listusers - 用户授权管理
/broadcast - 向所有用户发公告
/globallist - 查看所有用户的订阅汇总
/export /import - 备份与恢复订阅数据库
"""
    await update.message.reply_text(help_message, parse_mode='HTML')


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /check 命令（支持按标签检测）"""
    if not is_authorized(update):
        await _send_no_permission_msg(update)
        return
    store = get_storage()
    uid = update.effective_user.id

    # 检查是否指定了标签
    tag = context.args[0] if context.args else None

    if tag:
        # 按标签过滤（在当前用户的订阅中过滤）
        user_subs = store.get_by_user(uid)
        subscriptions = {
            url: data for url, data in user_subs.items()
            if tag in data.get('tags', [])
        }
        if not subscriptions:
            await update.message.reply_text(f"📭 标签 '{tag}' 下没有订阅")
            return
        msg_text = f"🔍 检测标签 '{tag}' 下的订阅 (共 {len(subscriptions)} 个)..."
    else:
        subscriptions = store.get_by_user(uid)
        if not subscriptions:
            await update.message.reply_text("📭 暂无订阅记录，请先发送订阅链接。")
            return
        msg_text = f"🔍 检测您的订阅 (共 {len(subscriptions)} 个)..."
    
    progress_msg = await update.message.reply_text(msg_text)
    
    # 异步并发检测（配合1GB内存，提升并发数以加快速度）
    results = []
    semaphore = asyncio.Semaphore(20)  # 最大化利用网络IO，大幅提速
    
    total_count = len(subscriptions)
    completed_count = 0
    last_update_time = time.time()
    
    async def check_one(url, data):
        nonlocal completed_count, last_update_time
        async with semaphore:
            try:
                # 使用原生异步解析，彻底消除线程池上下文切换开销
                parser_instance = await get_parser()
                result = await parser_instance.parse(url)
                
                # 检查流量是否已耗完
                remaining = result.get('remaining')
                if remaining is not None and remaining <= 0:
                    raise Exception("当前订阅流量已完全耗尽 (剩余 0 B)")
                    
                # 更新存储（保持卿主不变）
                store.add_or_update(url, result)
                
                res = {
                    'url': url,
                    'name': result.get('name', '未知'),
                    'remaining': remaining if remaining is not None else 0,
                    'expire_time': result.get('expire_time'),
                    'status': 'success'
                }
            except Exception as e:
                logger.error(f"检测失败 {url}: {e}", exc_info=True)
                
                # UX优化：自动无感清理坏死订阅
                store.remove(url)
                
                res = {
                    'url': url,
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
    
    # 并发检测（批处理写盘：多次 add_or_update 只触发一次 IO）
    store.begin_batch()
    tasks = [check_one(url, data) for url, data in subscriptions.items()]
    results = await asyncio.gather(*tasks)
    store.end_batch(save=True)

    # 删除进度消息
    try:
        await progress_msg.delete()
    except Exception as exc:
        logger.warning(f"删除进度消息失败: {exc}")

    # 生成汇总报告头
    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = sum(1 for r in results if r['status'] == 'failed')
    report = f"<b>📊 订阅检测报告</b>\n\n"
    report += f"总计: {len(results)} | ✅ 成功: {success_count} | ❌ 失效: {failed_count}\n"
    report += "—" * 20 + "\n"

    failed_results = [r for r in results if r['status'] == 'failed']
    if failed_results:
        report += "\n<b>❌ 失效订阅 (已自动清理):</b>\n\n"
        for item in failed_results:
            report += f"<b>{item['name']}</b>\n"
            report += f"<code>{item['url']}</code>\n"
            error_text = str(item.get('error', '未知错误'))
            if len(error_text) > 200:
                error_text = error_text[:200] + "..."
            report += f"原因: {error_text}\n\n"

    await send_long_message(update, report, parse_mode='HTML')

    # 成功的订阅逐条发送，附带操作按钮
    success_results = [r for r in results if r['status'] == 'success']
    for item in success_results:
        remaining = format_traffic(item['remaining'])
        url = item['url']
        msg = f"<b>✅ {item['name']}</b>\n"
        msg += f"剩余: {remaining}"
        if item.get('expire_time'):
            msg += f" | 到期: {item['expire_time']}"
        msg += f"\n<code>{url}</code>"

        # 图表生成自动发送已移除，请使用 /image 命令手动出图
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=make_sub_keyboard(url))


async def checkall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /checkall 命令（Owner 专属，检测所有用户的订阅）"""
    if not is_owner(update):
        await update.message.reply_text("❌ 该操作仅限 Owner 使用")
        return
    
    store = get_storage()
    subscriptions = store.get_all()
    
    if not subscriptions:
        await update.message.reply_text("📭 暂无任何订阅记录")
        return
        
    msg_text = f"🌍 <b>全局巡检启动</b>\n将检测所有用户的历史订阅 (共 {len(subscriptions)} 个)..."
    progress_msg = await update.message.reply_text(msg_text, parse_mode='HTML')
    
    # 异步并发检测（配合1GB内存，提升并发数以加快速度）
    results = []
    semaphore = asyncio.Semaphore(20)  # 最大化利用网络IO，大幅提速
    
    total_count = len(subscriptions)
    completed_count = 0
    last_update_time = time.time()
    
    async def check_one(url, data):
        nonlocal completed_count, last_update_time
        async with semaphore:
            try:
                # 使用原生异步解析，彻底消除线程池上下文切换开销
                parser_instance = await get_parser()
                result = await parser_instance.parse(url)
                
                # 检查流量是否已耗完
                remaining = result.get('remaining')
                if remaining is not None and remaining <= 0:
                    raise Exception("当前订阅流量已完全耗尽 (剩余 0 B)")
                    
                # 更新存储（传入其原有的 owner_uid）
                original_owner = data.get('owner_uid', 0)
                store.add_or_update(url, result, user_id=original_owner)
                
                res = {
                    'url': url,
                    'name': result.get('name', '未知'),
                    'owner_uid': original_owner,
                    'status': 'success'
                }
            except Exception as e:
                logger.error(f"全局检测失败 {url}: {e}", exc_info=True)
                
                # UX优化：自动无感清理坏死订阅
                store.remove(url)
                
                res = {
                    'url': url,
                    'name': data.get('name', '未知'),
                    'owner_uid': data.get('owner_uid', 0),
                    'status': 'failed',
                    'error': str(e)
                }
                
            # UX优化：动态更新进度条
            completed_count += 1
            current_time = time.time()
            if current_time - last_update_time > 2.0 or completed_count == total_count:
                try:
                    await progress_msg.edit_text(f"⏳ 全局检测中: {completed_count} / {total_count} 完成...")
                    last_update_time = current_time
                except:
                    pass
            return res
    
    # 并发检测（批处理写盘：多次 add_or_update 只触发一次 IO）
    store.begin_batch()
    tasks = [check_one(url, data) for url, data in subscriptions.items()]
    results = await asyncio.gather(*tasks)
    store.end_batch(save=True)

    # 删除进度消息
    try:
        await progress_msg.delete()
    except Exception as exc:
        logger.warning(f"删除进度消息失败: {exc}")

    # 生成汇总报告头
    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = sum(1 for r in results if r['status'] == 'failed')
    report = f"<b>🌍 全局巡检报告</b>\n\n"
    report += f"总计: {len(results)} | ✅ 存活: {success_count} | ❌ 失效: {failed_count}\n"
    report += "—" * 20 + "\n"

    failed_results = [r for r in results if r['status'] == 'failed']
    if failed_results:
        report += "\n<b>❌ 失效订阅 (已自动清理):</b>\n\n"
        for item in failed_results:
            report += f"<b>{item['name']}</b> (所属: <code>{item['owner_uid']}</code>)\n"
            report += f"<code>{item['url']}</code>\n"
            error_text = str(item.get('error', '未知错误'))
            if len(error_text) > 100:
                error_text = error_text[:100] + "..."
            report += f"原因: {error_text}\n\n"

    await send_long_message(update, report, parse_mode='HTML')


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /list 命令（按标签分组，每条附带删除按钮）"""
    if not is_authorized(update):
        await _send_no_permission_msg(update)
        return
    store = get_storage()
    uid = update.effective_user.id
    subscriptions = store.get_by_user(uid)

    if not subscriptions:
        await update.message.reply_text("📭 您没有订阅，请先发送订阅链接。")
        return

    # 从用户自己的订阅中提取标签（不暴露其他用户的标签）
    tags = sorted({t for data in subscriptions.values() for t in data.get('tags', [])})
    untagged = {url: data for url, data in subscriptions.items() if not data.get('tags')}

    header = f"<b>📋 我的订阅列表 (共 {len(subscriptions)} 个)</b>"
    await update.message.reply_text(header, parse_mode='HTML')

    async def send_sub_item(url, data, tag_label=""):
        """发送单条订阅，附带操作按钮"""
        label = f"{tag_label}" if tag_label else "📦 未分组"
        msg = f"{label} — <b>{data['name']}</b>\n<code>{url}</code>"
        keyboard = [
            [
                InlineKeyboardButton("🔄 重检", callback_data=get_short_callback_data("recheck", url)),
                InlineKeyboardButton("🏷️ 标签", callback_data=get_short_callback_data("tag", url)),
                InlineKeyboardButton("🗑️ 删除", callback_data=get_short_callback_data("delete", url))
            ]
        ]
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    # 显示有标签的订阅（仅当前用户自己的标签）
    for tag in tags:
        tagged_subs = {url: data for url, data in subscriptions.items() if tag in data.get('tags', [])}
        for url, data in tagged_subs.items():
            await send_sub_item(url, data, tag_label=f"🏷️ {tag}")

    # 显示无标签的订阅
    for url, data in untagged.items():
        await send_sub_item(url, data)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /stats 命令（统计信息 + 系统状态）"""
    if not is_authorized(update):
        await _send_no_permission_msg(update)
        return
    store = get_storage()
    uid = update.effective_user.id
    # 普通用户看自己的统计； Owner 可使用 /globallist 查看全局
    stats = store.get_user_statistics(uid)
    
    msg = "📊 <b>统计与状态看板</b>\n\n"
    msg += f"<b>订阅总数:</b> {stats['total']}\n"
    msg += f"<b>有效订阅:</b> {stats['active']}\n"
    msg += f"<b>已过期:</b> {stats['expired']}\n"
    msg += f"<b>总流量:</b> {format_traffic(stats['total_traffic'])}\n"
    msg += f"<b>剩余流量:</b> {format_traffic(stats['total_remaining'])}\n"
    
    if stats['tags']:
        msg += f"<b>标签:</b> {', '.join(stats['tags'])}\n"
        
    if is_owner(update):
        try:
            import psutil
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            msg += "\n🖥 <b>系统运行状态 (Owner)</b>\n"
            msg += f"• CPU: {cpu}%\n"
            msg += f"• 内存: {mem.percent}% ({format_traffic(mem.available)} 可用)\n"
            msg += f"• 磁盘: {disk.percent}% ({format_traffic(disk.free)} 剩余)\n"
        except Exception as e:
            logger.warning(f"获取系统状态失败: {e}")

    await update.message.reply_text(msg, parse_mode='HTML')


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """广播系统通知给所有授权用户 (Owner Only)"""
    if not is_owner(update):
        await update.message.reply_text("❌ 该操作权限仅限 Owner")
        return
    
    if not context.args:
        await update.message.reply_text("使用方式: /broadcast <通知内容>")
        return
    
    content = " ".join(context.args)
    broadcast_msg = f"📢 <b>系统通知 (来自 Owner)</b>\n\n{content}"
    
    status_msg = await update.message.reply_text("📡 正在准备发送广播...")
    
    # 获取所有授权用户
    users = user_manager.get_all()
    success, fail = 0, 0
    
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=broadcast_msg, parse_mode='HTML')
            success += 1
        except Exception as e:
            logger.warning(f"广播发送失败 UID:{uid}: {e}")
            fail += 1
            
    await status_msg.edit_text(f"✅ 广播发送完毕\n成功: {success}\n失败: {fail}")


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /delete 命令 - 根据参数删除指定订阅"""
    if not is_authorized(update):
        await _send_no_permission_msg(update)
        return
    store = get_storage()

    if not context.args:
        uid = update.effective_user.id
        subscriptions = store.get_by_user(uid)
        if not subscriptions:
            await update.message.reply_text("📭 您没有订阅可删除")
            return
        await update.message.reply_text(
            "📋 请使用 /list 查看订阅列表，点击每条下方的 🗑️ 按钮直接删除\n"
            "或使用: <code>/delete &lt;订阅链接&gt;</code>",
            parse_mode='HTML'
        )
        return

    url = context.args[0].strip()
    uid = update.effective_user.id
    # 限定在当前用户自己的订阅中查找（Owner 也如此，防止展露他人订阅链接）
    user_subs = store.get_by_user(uid) if not is_owner(update) else store.get_all()
    sub_data = user_subs.get(url)
    if not sub_data:
        await update.message.reply_text("❌ 未找到该订阅，请确认链接是否正确")
        return

    # 专家级加固：二次确认
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认持久删除", callback_data=get_short_callback_data("del_confirm", url)),
            InlineKeyboardButton("❌ 取消", callback_data="del_cancel")
        ]
    ]
    await update.message.reply_text(
        f"⚠️ <b>安全确认</b>\n\n确定要永久删除以下订阅吗？\n名称: <b>{sub_data['name']}</b>\n链接: <code>{url}</code>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /export 命令"""
    if not is_owner(update):
        await update.message.reply_text("❌ 该操作仅限 Owner (超级管理员) 使用")
        return
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


async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /import 命令"""
    if not is_owner(update):
        await update.message.reply_text("❌ 该操作仅限 Owner (超级管理员) 使用")
        return
    context.user_data['awaiting_import'] = True
    await update.message.reply_text(
        "请上传由 /export 导出的 JSON 文件，我会自动导入到当前订阅列表。"
    )

async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加授权用户 (Owner Only)"""
    if not is_owner(update):
        await update.message.reply_text("❌ 该操作仅限 Owner 使用")
        return
    if not context.args:
        await update.message.reply_text("使用方式: /adduser <用户ID>")
        return
    
    uid_str = context.args[0]
    if not uid_str.isdigit():
        await update.message.reply_text("❌ 无效的用户 ID")
        return
    
    uid = int(uid_str)
    if user_manager.add_user(uid):
        await update.message.reply_text(f"✅ 已成功授权用户: <code>{uid}</code>", parse_mode='HTML')
    else:
        await update.message.reply_text(f"ℹ️ 该用户已在授权名单中")

async def del_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """移除授权用户 (Owner Only)"""
    if not is_owner(update):
        await update.message.reply_text("❌ 该操作仅限 Owner 使用")
        return
    if not context.args:
        await update.message.reply_text("使用方式: /deluser <用户ID>")
        return
    
    uid_str = context.args[0]
    if not uid_str.isdigit():
        await update.message.reply_text("❌ 无效的用户 ID")
        return
    
    uid = int(uid_str)
    if uid == config.OWNER_ID:
        await update.message.reply_text("❌ 无法移除 Owner 自己")
        return

    if user_manager.remove_user(uid):
        await update.message.reply_text(f"✅ 已成功移除授权用户: <code>{uid}</code>", parse_mode='HTML')
    else:
        await update.message.reply_text(f"❌ 名单中未找到该用户")

async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看授权名单 (Owner Only)"""
    if not is_owner(update):
        await update.message.reply_text("❌ 该操作仅限 Owner 使用")
        return
    
    users = user_manager.get_all()
    if not users:
        await update.message.reply_text("📭 当前无授权用户")
        return
    
    msg = "<b>👥 授权用户名单</b>\n\n"
    for uid in users:
        tag = " (Owner)" if user_manager.is_owner(uid) else ""
        msg += f"• <code>{uid}</code>{tag}\n"
    
    await update.message.reply_text(msg, parse_mode='HTML')


async def globallist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """全局订阅总览：按用户分组展示所有订阅 (Owner Only)"""
    if not is_owner(update):
        await update.message.reply_text("❌ 该操作仅限 Owner 使用")
        return

    store = get_storage()
    grouped = store.get_grouped_by_user()

    if not grouped:
        await update.message.reply_text("📭 当前暂无任何订阅")
        return

    total_subs = sum(len(subs) for subs in grouped.values())
    report = f"<b>👑 全局订阅总览</b>\n共 {total_subs} 条订阅 / {len(grouped)} 个用户\n\n"

    for uid, subs in grouped.items():
        report += f"━━━━━━━━━━━━━━━━━━━━\n"
        report += f"<b>👤 用户 <code>{uid}</code></b> ({len(subs)} 条)\n"
        report += f"━━━━━━━━━━━━━━━━━━━━\n"
        for url, data in subs.items():
            name = data.get('name', '未知')
            remaining = data.get('remaining', 0)
            expire = data.get('expire_time', '')
            # 状态标记
            if remaining is not None and remaining <= 0:
                status = "❌"
            else:
                status = "✅"
            line = f"  {status} <b>{name}</b>"
            if remaining:
                line += f" | 剩余 {format_traffic(remaining)}"
            if expire:
                line += f" | 到期 {expire}"
            report += line + "\n"
        report += "\n"

    await send_long_message(update, report, parse_mode='HTML')


async def to_yaml_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """回复一个 txt 文件并转换为 yaml"""
    if not is_authorized(update):
        await _send_no_permission_msg(update)
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("❌ 请回复包含节点列表的 TXT 文件消息使用此命令")
        return
    
    doc = update.message.reply_to_message.document
    if not doc.file_name.lower().endswith('.txt'):
        await update.message.reply_text("❌ 仅支持对 .txt 文件进行转换")
        return

    proc_msg = await update.message.reply_text("⏳ 正在进行格式转换 (TXT -> YAML)...")
    try:
        file = await doc.get_file()
        content = await file.download_as_bytearray()
        
        # 保存到 raw 目录
        raw_path = ws_manager.save_raw_file(doc.file_name, bytes(content))
        
        # 转换逻辑
        converter = SSNodeConverter()
        if converter.parse_txt_file(raw_path):
            output_name = doc.file_name.rsplit('.', 1)[0] + ".yaml"
            output_path = os.path.join(ws_manager.yaml_dir, output_name)
            if converter.to_yaml(output_path):
                with open(output_path, 'rb') as f:
                    await update.message.reply_document(document=f, filename=output_name, caption="✅ 转换成功 (Clash YAML 格式)")
                await proc_msg.delete()
            else:
                await proc_msg.edit_text("❌ YAML 序列化失败")
        else:
            await proc_msg.edit_text("❌ 文件解析失败，未找到有效代理节点")
    except Exception as e:
        await proc_msg.edit_text(f"❌ 转换出错: {e}")

async def to_txt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """回复一个 yaml 文件并转换为 txt"""
    if not is_authorized(update):
        await _send_no_permission_msg(update)
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("❌ 请回复包含 Clash 配置的 YAML 文件消息使用此命令")
        return
    
    doc = update.message.reply_to_message.document
    if not doc.file_name.lower().endswith(('.yaml', '.yml')):
        await update.message.reply_text("❌ 仅支持对 .yaml/.yml 文件进行转换")
        return

    proc_msg = await update.message.reply_text("⏳ 正在进行格式转换 (YAML -> TXT)...")
    try:
        file = await doc.get_file()
        content = await file.download_as_bytearray()
        
        raw_path = ws_manager.save_raw_file(doc.file_name, bytes(content))
        
        converter = SSNodeConverter()
        if converter.parse_yaml_file(raw_path):
            output_name = doc.file_name.rsplit('.', 1)[0] + ".txt"
            output_path = os.path.join(ws_manager.txt_dir, output_name)
            if converter.to_txt(output_path):
                with open(output_path, 'rb') as f:
                    await update.message.reply_document(document=f, filename=output_name, caption="✅ 转换成功 (明文 TXT 格式)")
                await proc_msg.delete()
            else:
                await proc_msg.edit_text("❌ TXT 序列化失败")
        else:
            await proc_msg.edit_text("❌ 文件解析失败，未找到有效 proxies")
    except Exception as e:
        await proc_msg.edit_text(f"❌ 转换出错: {e}")

async def deepcheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """真实连通性测活 (实验性)"""
    if not is_authorized(update):
        await _send_no_permission_msg(update)
        return

    
    # 优先检测回复的文件
    target_file = None
    if update.message.reply_to_message and update.message.reply_to_message.document:
        doc = update.message.reply_to_message.document
        file = await doc.get_file()
        content = await file.download_as_bytearray()
        target_file = ws_manager.save_raw_file(doc.file_name, bytes(content))
    else:
        await update.message.reply_text("❌ 请回复包含节点或订阅的 TXT/YAML 文件消息使用此命令")
        return

    proc_msg = await update.message.reply_text("⏳ 正在初始化深度检测引擎 (Mihomo)...")
    
    async def status_callback(msg: str):
        try:
            # Telegram 文本防抖：如果内容相同则不发送
            if proc_msg.text == msg: return
            await proc_msg.edit_text(msg)
        except Exception:
            pass # 忽略频率限制报错

    try:
        # 运行深度测试
        # 设置 clean_policy='no' 避免修改用户原始文件，改为导出通过文件
        await _async_run_node_latency_test(
            [target_file], 
            mode='auto', 
            clean_policy='no', 
            export_policy='yes', 
            status_callback=status_callback
        )
        
        # 检查是否生成了通过文件 (简单判断)
        yaml_files = sorted(os.listdir(ws_manager.yaml_dir), key=lambda x: os.path.getmtime(os.path.join(ws_manager.yaml_dir, x)), reverse=True)
        if yaml_files:
            latest = yaml_files[0]
            latest_path = os.path.join(ws_manager.yaml_dir, latest)
            # 如果是刚生成的 (1分钟内)
            if time.time() - os.path.getmtime(latest_path) < 60:
                with open(latest_path, 'rb') as f:
                    await update.message.reply_document(
                        document=f, 
                        filename=latest, 
                        caption="✅ 深度测活完成！已自动过滤并导出存活节点。"
                    )
                await proc_msg.delete()
            else:
                await proc_msg.edit_text("✅ 检测完成，但未发现有效活节点或导出失败。")
        else:
            await proc_msg.edit_text("✅ 检测完成，未产生导出文件。")
            
    except Exception as e:
        logger.error(f"Deepcheck failed: {e}")
        await proc_msg.edit_text(f"❌ 深度检测失败: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理文件上传(智能检测订阅链接)"""
    if not is_authorized(update):
        await _send_no_permission_msg(update)
        return
    document = update.message.document
    file_type = InputDetector.detect_file_type(document.file_name)
    
    if file_type == 'unknown':
        await update.message.reply_text("❌ 不支持的文件类型,请上传 txt/yaml 文件；导入请使用 /import 后上传 json")
        return
    
    processing_msg = await update.message.reply_text(f"📄 正在分析{file_type.upper()}文件...")
    
    # #1 内存优化：限制上传文件大小 (最大 5MB)
    if document.file_size > 5 * 1024 * 1024:
        await processing_msg.edit_text("❌ 文件过大 (超过 5MB)，出于服务器安全考虑拒绝处理。")
        return

    try:
        # 下载文件
        file = await document.get_file()
        file_content = await file.download_as_bytearray()
        content_bytes = bytes(file_content)
        
        if file_type == 'json':
            if not is_owner(update):
                await processing_msg.edit_text("❌ 仅 Owner 允许执行 JSON 导入")
                return
            if not context.user_data.get('awaiting_import'):
                await processing_msg.edit_text("❌ 请先发送 /import，再上传导出的 JSON 文件")
                return

            loop = asyncio.get_event_loop()
            os.makedirs('data', exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            import_file = f"data/import_{timestamp}.json"

            with open(import_file, 'wb') as f:
                f.write(content_bytes)

            imported_count = await loop.run_in_executor(None, get_storage().import_from_file, import_file)
            await loop.run_in_executor(None, os.remove, import_file)
            context.user_data.pop('awaiting_import', None)

            await processing_msg.edit_text(f"✅ 导入完成，共导入 {imported_count} 条订阅")
            return
        # 智能检测: 优先查找订阅链接
        if file_type == 'txt':
            subscription_urls = FileHandler.extract_subscription_urls(content_bytes)

            if subscription_urls:
                await processing_msg.edit_text(
                    f"🔗 发现 {len(subscription_urls)} 个订阅链接，并发解析中..."
                )

                store = get_storage()
                store.begin_batch()
                semaphore = asyncio.Semaphore(20)  # 提升文件批量解析时的并发度

                file_owner_uid = update.effective_user.id  # 文件上传者 UID，供闭包引用

                async def parse_one(idx, url):
                    async with semaphore:
                        try:
                            # 修复：get_parser() 是协程，必须先 await 获取实例，再 await 调用 parse()
                            parser_instance = await get_parser()
                            result = await parser_instance.parse(url)
                            store.add_or_update(url, result, user_id=file_owner_uid)  # 绝对不能省略 user_id
                            return {'index': idx, 'url': url, 'data': result, 'status': 'success'}
                        except Exception as e:
                            logger.error(f"订阅解析失败 {url}: {e}")
                            return {'index': idx, 'url': url, 'error': str(e), 'status': 'failed'}

                try:
                    tasks = [parse_one(i, url) for i, url in enumerate(subscription_urls, 1)]
                    results = await asyncio.gather(*tasks)
                finally:
                    store.end_batch(save=True)

                try:
                    await processing_msg.delete()
                except Exception as exc:
                    logger.warning(f"删除进度消息失败: {exc}")

                # 发送每个订阅的详细信息
                for res in sorted(results, key=lambda r: r['index']):
                    if res['status'] == 'success':
                        data = res['data']
                        message = f"<b>📊 订阅 {res['index']}</b>\n\n"
                        message += format_subscription_info(data, res['url'])
                        await update.message.reply_text(message, parse_mode='HTML', reply_markup=make_sub_keyboard(res['url']))
                    else:
                        await update.message.reply_text(
                            f"❌ <b>订阅 {res['index']}</b> 解析失败\n错误: {res['error']}",
                            parse_mode='HTML'
                        )

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
        parser_instance = await get_parser()
        node_stats = await parser_instance._analyze_nodes(nodes)
        
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

        # 自动出图已移除，请使用 /image 手动出图
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
        parser_instance = await get_parser()
        node_stats = await parser_instance._analyze_nodes(nodes)
        
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

        # 自动出图已移除
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
    """处理订阅链接（支持受控并发）"""
    text = update.message.text.strip()
    urls = [line.strip() for line in text.split('\n') if line.strip()]
    uid = update.effective_user.id

    semaphore = asyncio.Semaphore(20)
    store = get_storage()
    store.begin_batch()

    async def process_one(url):
        if not is_valid_url(url):
            await update.message.reply_text(f"❌ 无效的 URL: {url[:50]}...")
            return

        processing_msg = await update.message.reply_text("⏳ 正在解析...")

        async with semaphore:
            try:
                parser_instance = await get_parser()
                result = await parser_instance.parse(url)

                store.add_or_update(url, result, user_id=uid)  # 传入用户 ID
                message = format_subscription_info(result, url)

                try:
                    await processing_msg.delete()
                except Exception as exc:
                    logger.warning(f"删除进度消息失败: {exc}")

                await update.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=make_sub_keyboard(url)
                )

            except Exception as e:
                error_msg = str(e)
                if len(error_msg) > 500:
                    error_msg = error_msg[:500] + "..."
                try:
                    await processing_msg.edit_text(f"❌ 解析失败: {error_msg}")
                except Exception:
                    await update.message.reply_text(f"❌ 解析失败: {error_msg}")

    try:
        tasks = [process_one(url) for url in urls]
        await asyncio.gather(*tasks)
    finally:
        store.end_batch(save=True)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮回调"""
    query = update.callback_query
    await query.answer()
    # 按钮回调同样需要鉴权（防止其他用户伪造 callback_data）
    if not is_authorized(update):
        await query.answer("⛔ 无权限", show_alert=True)
        return
    
    data = query.data
    try:
        action, hash_key = data.split(':', 1)
    except ValueError:
        await query.answer("数据异常", show_alert=True)
        return

    # tag_apply 只需要 hash_key 存的是 url:tag，单独处理
    if action == 'tag_apply':
        # hash_key 此处存储 "url_hash|tag" 格式
        parts = hash_key.split('|', 1)
        if len(parts) != 2:
            await query.answer("数据异常", show_alert=True)
            return
        url_hash, tag = parts[0], parts[1]
        _cleanup_url_cache()
        cache_entry = url_cache.get(url_hash)
        url = cache_entry.get('url') if cache_entry else None
        if not url:
            await query.answer("按钮已过期，请重新操作", show_alert=True)
            return
        store = get_storage()
        if store.add_tag(url, tag):
            await query.edit_message_text(f"✅ 已添加标签: {tag}\n订阅: {store.get_all().get(url, {}).get('name', url)}")
        else:
            await query.answer(f"标签 '{tag}' 已存在", show_alert=True)
            await query.edit_message_text(f"ℹ️ 标签 '{tag}' 已存在，无需重复添加")
        return

    if action == 'tag_new':
        # 用户选择「新建标签」，回退到手动输入流程
        _cleanup_url_cache()
        cache_entry = url_cache.get(hash_key)
        url = cache_entry.get('url') if cache_entry else None
        if not url:
            await query.answer("按钮已过期，请重新操作", show_alert=True)
            return
        store = get_storage()
        sub_name = store.get_all().get(url, {}).get('name', url)
        await query.edit_message_text(
            f"请发送新标签名称：\n订阅: {sub_name}"
        )
        context.user_data['pending_tag_url'] = url
        return

    _cleanup_url_cache()
    cache_entry = url_cache.get(hash_key)
    url = cache_entry.get('url') if cache_entry else None
    if not url:
        await query.answer("交互按钮已过期，请重新发送链接进行操作！", show_alert=True)
        return

    store = get_storage()

    if action == 'recheck':
        # 重新检测
        await query.edit_message_text("⏳ 正在重新检测...")
        try:
            parser_instance = await get_parser()
            result = await parser_instance.parse(url)
            store.add_or_update(url, result)

            message = format_subscription_info(result, url)
            # 重新检测不再自动弹图
            await query.edit_message_text(
                message,
                parse_mode='HTML',
                reply_markup=make_sub_keyboard(url)
            )
        except Exception as e:
            await query.edit_message_text(f"❌ 检测失败: {str(e)}")

    elif action == 'ping':
        # 并发 TCP 真实测速
        await query.edit_message_text("⚡ 正在执行真实节点并发测速，请稍候...")
        try:
            # 需要再解析一次拿到 nodes 列表，或者从结果中直接测。此处采取再解析保障新鲜度
            parser_instance = await get_parser()
            result = await parser_instance.parse(url)
            nodes = result.get('_raw_nodes', [])
            if not nodes:
                # 若解析没出raw nodes，回退一下
                await query.edit_message_text("❌ 当前格式不支持直接获取节点列表测速。")
                return

            alive_count, total_count, alive_nodes = await latency_tester.ping_all_nodes(nodes, concurrency=20)
            
            ping_report = f"<b>⚡ 测速报告</b>\n"
            ping_report += f"总计: {total_count} | ✅ 存活: {alive_count} | ❌ 失效: {total_count - alive_count}\n"
            ping_report += "—" * 20 + "\n"
            
            if alive_nodes:
                ping_report += "\n<b>🏆 Top 5 最快节点:</b>\n"
                for i, n in enumerate(alive_nodes[:5]):
                    ping_report += f"{i+1}. {n['name']} - <code>{n['latency']}ms</code>\n"
            
            # 由于可能很长，调用统一超长消息拦截器。这里简化发送总结，避免刷屏。
            await query.message.reply_text(ping_report, parse_mode='HTML')
            await query.message.delete()
        except Exception as e:
            await query.edit_message_text(f"❌ 测速过程发生错误: {str(e)}")

    elif action == 'delete':
        # 触发二次确认
        sub_name = store.get_all().get(url, {}).get('name', url)
        keyboard = [
            [
                InlineKeyboardButton("💥 确认删除", callback_data=get_short_callback_data("del_confirm", url)),
                InlineKeyboardButton("🔙 返回", callback_data=get_short_callback_data("recheck", url)) # 借用 recheck 返回
            ]
        ]
        await query.edit_message_text(
            f"❓ <b>确定删除订阅吗？</b>\n\n名称: {sub_name}\n此操作不可撤销。",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif action == 'del_confirm':
        # 执行最终删除（带 owner_uid 校验，防止跨用户删除）
        operator_uid = update.effective_user.id
        if store.remove(url, operator_uid=operator_uid, require_owner=not is_owner(update)):
            await query.edit_message_text("🗑️ <b>订阅已永久从数据库移除</b>", parse_mode='HTML')
        else:
            await query.edit_message_text("❌ 删除失败：您无权删除他人的订阅，或该记录已被移除")

    elif action == 'del_cancel':
        await query.edit_message_text("🗳️ <b>已安全取消删除操作</b>", parse_mode='HTML')

    elif action == 'tag':
        # 弹出当前用户自己的标签候选按钮（完全隔离，不暴露其他用户的标签）
        operator_uid = update.effective_user.id
        user_subs = store.get_by_user(operator_uid)
        existing_tags = sorted({t for data in user_subs.values() for t in data.get('tags', [])})
        sub_name = user_subs.get(url, {}).get('name', url)
        url_hash = hash_key

        if existing_tags:
            # 构造候选按钮：每行2个，末尾加「新建」
            tag_buttons = []
            row = []
            for tag in existing_tags:
                # callback_data 格式: tag_apply:<url_hash>|<tag>
                cb = f"tag_apply:{url_hash}|{tag}"
                if len(cb) <= 64:
                    row.append(InlineKeyboardButton(f"🏷 {tag}", callback_data=cb))
                if len(row) == 2:
                    tag_buttons.append(row)
                    row = []
            if row:
                tag_buttons.append(row)
            tag_buttons.append([InlineKeyboardButton("✏️ 新建标签", callback_data=get_short_callback_data("tag_new", url))])
            await query.edit_message_text(
                f"为 <b>{sub_name}</b> 选择或新建标签：",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(tag_buttons)
            )
        else:
            # 没有已有标签，直接进入手动输入
            await query.edit_message_text(
                f"请发送标签名称：\n订阅: {sub_name}"
            )
            context.user_data['pending_tag_url'] = url


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理普通消息(智能识别输入类型)"""
    if not is_authorized(update):
        await _send_no_permission_msg(update)
        return
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
    logger.info(" GIPSON_CHECK - 智能订阅检测机器人项目 ")
    logger.info("支持: IP地理位置、文件处理、智能输入识别、内核测速")
    logger.info("=" * 60)
    logger.info("启动 Telegram 机场订阅解析机器人 [V3 (Async Native)]...")
    
    # 构建应用 (挂载关闭回调)
    application = Application.builder().token(BOT_TOKEN).post_shutdown(_on_shutdown).build()

    # 注册命令处理器
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("checkall", checkall_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CommandHandler("import", import_command))
    application.add_handler(CommandHandler("adduser", add_user_command))
    application.add_handler(CommandHandler("deluser", del_user_command))
    application.add_handler(CommandHandler("listusers", list_users_command))
    application.add_handler(CommandHandler("globallist", globallist_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("to_yaml", to_yaml_command))
    application.add_handler(CommandHandler("to_txt", to_txt_command))
    application.add_handler(CommandHandler("deepcheck", deepcheck_command))
    application.add_handler(CommandHandler("delete", delete_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    # [性能优化] 启动后台定期清理 URL 缓存任务 (每 10 分钟一次)
    if application.job_queue:
        application.job_queue.run_repeating(_periodic_url_cache_cleanup, interval=600, first=600)

    # 文件处理器(优先级高)
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # 文本消息处理器
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 打印当前功能开关配置摘要
    config.print_config_summary()

    # 旧数据迁移：将历史订阅（无 owner_uid）归属到 Owner 名下
    if config.OWNER_ID > 0:
        migrated = get_storage().migrate_subscriptions(config.OWNER_ID)
        if migrated:
            logger.info(f"✅ 历史数据迁移完成，{migrated} 条订阅已归属到 Owner (UID: {config.OWNER_ID})")

    # 根据开关条件启动定时监控
    if config.ENABLE_MONITOR:
        monitor.start_monitor(application, get_storage(), get_parser, ALLOWED_USER_IDS, ws_manager)
    else:
        logger.info("🔕 定时监控已关闭（ENABLE_MONITOR=False）")

    # 启动机器人
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
