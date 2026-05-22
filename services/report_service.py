"""用户侧文案报表构建器。"""

from __future__ import annotations

import logging

from shared.format_helpers import format_traffic

logger = logging.getLogger(__name__)


def build_start_message(*, owner_mode: bool) -> str:
    owner_tip = ""
    if owner_mode:
        owner_tip = (
            "\n<b>管理员入口</b>\n高频运维可用 /checkall 和 /backup；低频管理请进入 Web Admin。"
        )

    return f"""
<b>欢迎使用 dingyue-check</b>

主路径很简单：
1) 发送<b>订阅链接</b>，自动检查并保存
2) 使用 <code>/list</code> 管理订阅和标签
3) 使用 <code>/check</code> 复查订阅状态

也可以：
上传 TXT / YAML 文件做节点转换
查看即将到期或低流量订阅提醒

<b>直接开始</b>
直接发送订阅链接
直接上传 TXT / YAML 文件或粘贴节点文本

<b>常用命令</b>
/list - 查看我的订阅
/check - 检测我的订阅状态
/to_yaml - TXT 节点转 YAML
/to_txt - YAML 转 TXT
/help - 查看完整帮助{owner_tip}

<b>现在就发送订阅链接或上传文件开始使用。</b>
""".strip()


def build_help_message(*, owner_mode: bool) -> str:
    message = """
<b>使用帮助</b>

<b>一、主路径</b>
发送订阅链接：自动解析、检查并保存到你的订阅列表
/list：查看订阅，继续复查、打标签或删除
/check：复查全部订阅；/check [标签] 只检查某个标签

<b>二、常用命令</b>
/list - 查看订阅列表
/check - 检测我的全部订阅
/stats - 查看我的订阅统计
/delete - 查看删除帮助

<b>三、格式转换</b>
/to_yaml - 回复 TXT 文件，将节点列表转为 Clash YAML
/to_txt - 回复 YAML 文件，将配置转为 TXT 节点列表

<b>四、检测边界</b>
/check 主要检查订阅状态、流量、到期和节点数量
节点连通性测试是显式操作，不会在每次 /check 中重跑
/deepcheck 仅在回复 TXT / YAML 文件时做更深入的节点测试

<b>五、自动预警规则</b>
到期时间 <= 3 天，会触发到期预警
剩余流量 < 10% 或低于 5 GB，会触发流量预警
/check 结果中的“需关注”与自动预警使用同一规则
""".strip()
    if owner_mode:
        message += """

<b>七、管理员增强功能</b>
/checkall - 检测所有用户订阅
/backup /restore - 备份与恢复完整数据
/broadcast - 向授权用户发送通知
授权、审计、导出、全局订阅和聚合订阅等低频管理动作建议在 Web Admin 中完成
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
