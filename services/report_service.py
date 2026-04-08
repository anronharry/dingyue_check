"""用户侧文案报表构建器。"""
from __future__ import annotations

import logging

from shared.format_helpers import format_traffic

logger = logging.getLogger(__name__)


def build_start_message(*, owner_mode: bool) -> str:
    owner_tip = ""
    if owner_mode:
        owner_tip = (
            "\n<b>管理员增强功能</b>\n"
            "你还可以管理授权用户，并查看全部用户上传和检测过的订阅。"
        )

    return f"""
<b>欢迎使用订阅转换与检测机器人</b>

我可以帮你完成 3 件事：
1) 发送<b>订阅链接</b>，帮你检测是否可用
2) 上传<b>TXT / YAML 文件</b>，帮你互相转换
3) 自动提醒<b>即将到期</b>和<b>低流量</b>订阅

<b>快速使用</b>
直接发送订阅链接
直接上传 TXT / YAML 文件
直接粘贴节点文本（如 `vmess://`、`ss://`）

<b>常用命令</b>
/check - 检测我的订阅状态
/list - 查看我的订阅
/to_yaml - TXT 节点转 YAML
/to_txt - YAML 转 TXT
/help - 查看完整帮助{owner_tip}

<b>现在就发送订阅链接或上传文件开始使用。</b>
""".strip()


def build_help_message(*, owner_mode: bool) -> str:
    message = """
<b>使用帮助</b>

<b>一、日常怎么用</b>
发送订阅链接：自动解析并保存到你的订阅列表
上传 TXT 文件：自动识别是“订阅链接列表”还是“节点列表”
上传 YAML 文件：可分析内容，或配合命令转换为 TXT
粘贴节点文本：自动识别并统计节点数量与协议分布

<b>二、最常用命令</b>
/check - 检测我的全部订阅
/check [标签] - 仅检测某个标签下的订阅
/list - 查看订阅列表，并可直接重新检测 / 加标签 / 删除
/stats - 查看我的订阅统计

<b>三、格式转换</b>
/to_yaml - 回复一个 TXT 文件使用，将节点列表转为 Clash YAML
/to_txt - 回复一个 YAML 文件使用，将配置转为明文 TXT 节点列表

<b>四、深度检测</b>
/deepcheck - 回复一个 TXT / YAML 文件使用，做更深入的节点连通性测试

<b>五、删除与整理</b>
/delete - 查看删除帮助
/delete &lt;订阅链接&gt; - 删除指定订阅
/list 与检测结果下方按钮也支持快捷操作

<b>六、自动预警规则</b>
到期时间 <= 3 天，会触发到期预警
剩余流量 < 10% 或低于 5 GB，会触发流量预警
/check 结果中的“需关注”与自动预警使用同一规则
""".strip()
    if owner_mode:
        message += """

<b>七、管理员增强功能</b>
/adduser /deluser /listusers - 管理授权用户
/allowall /denyall - 一键切换公开访问模式
/usageaudit - 查看最近谁用过机器人、检测了哪些链接
/checkall - 检测所有用户订阅
/globallist - 查看全局订阅与剩余流量
/broadcast - 向所有授权用户发送通知
/export /import - 导出或导入订阅数据库
/backup /restore - 备份与恢复完整数据
""".rstrip()
    return message


def build_stats_message(*, stats: dict, owner_mode: bool) -> str:
    message = "<b>统计与状态看板</b>\n\n"
    message += f"<b>订阅总数:</b> {stats['total']}\n"
    message += f"<b>有效订阅:</b> {stats['active']}\n"
    message += f"<b>已过期:</b> {stats['expired']}\n"
    message += f"<b>总流量:</b> {format_traffic(stats['total_traffic'])}\n"
    message += f"<b>剩余流量:</b> {format_traffic(stats['total_remaining'])}\n"
    if stats["tags"]:
        message += f"<b>标签:</b> {', '.join(stats['tags'])}\n"

    if owner_mode:
        try:
            import psutil

            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            message += "\n<b>系统运行状态（管理员）</b>\n"
            message += f"- CPU: {cpu}%\n"
            message += f"- 内存: {mem.percent}% ({format_traffic(mem.available)} 可用)\n"
            message += f"- 磁盘: {disk.percent}% ({format_traffic(disk.free)} 剩余)\n"
        except Exception as exc:
            logger.warning("获取系统状态失败: %s", exc)

    return message
