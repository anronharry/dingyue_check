"""Owner/admin report builders and export helpers."""

from __future__ import annotations

import html
import os
from datetime import datetime


class AdminService:
    def __init__(self, *, get_storage, user_manager, owner_id: int, format_traffic, access_service, usage_audit_service):
        self.get_storage = get_storage
        self.user_manager = user_manager
        self.owner_id = owner_id
        self.format_traffic = format_traffic
        self.access_service = access_service
        self.usage_audit_service = usage_audit_service

    def build_globallist_report(self) -> str | None:
        store = self.get_storage()
        grouped = store.get_grouped_by_user()
        others_grouped = {uid: subs for uid, subs in grouped.items() if uid != self.owner_id}
        if not others_grouped:
            return None

        total_subs = sum(len(subs) for subs in others_grouped.values())
        report = (
            f"📝 <b>全局订阅总览</b>\n"
            f"共 <b>{total_subs}</b> 条订阅 / <b>{len(others_grouped)}</b> 个用户\n"
        )
        report += "—" * 20 + "\n\n"

        sorted_users = sorted(others_grouped.items(), key=lambda item: item[0])
        for uid, subs in sorted_users:
            ordered_subs = sorted(
                subs.items(),
                key=lambda item: (
                    0 if item[1].get("remaining") is not None and item[1].get("remaining") <= 0 else 1,
                    item[1].get("expire_time") or "9999-99-99",
                    item[1].get("remaining") if item[1].get("remaining") is not None else float("inf"),
                    item[1].get("name", "未知"),
                ),
            )
            report += f"🔹 <b>用户 <code>{uid}</code></b>（{len(subs)} 条）\n"
            for url, data in ordered_subs:
                name = html.escape(data.get("name", "未知"))
                remaining = data.get("remaining")
                expire = data.get("expire_time", "")
                status = "❌" if remaining is not None and remaining <= 0 else "✅"

                line = f"  └ {status} <b>{name}</b>"
                if remaining is not None:
                    line += f" | 剩余: {self.format_traffic(remaining)}"
                if expire:
                    line += f" | 到期: {expire[:10]}"
                line += f"\n    <code>{url}</code>"
                report += line + "\n"
            report += "\n"
        return report

    def build_user_list_message(self) -> str | None:
        users = self.user_manager.get_all()
        if not users:
            return None

        public_mode = "开启" if self.access_service.is_allow_all_users_enabled() else "关闭"
        message = f"<b>👥 授权用户名单</b>\n全员可用模式：<b>{public_mode}</b>\n\n"
        for uid in sorted(users):
            tag = " (Owner)" if self.user_manager.is_owner(uid) else ""
            message += f"• <code>{uid}</code>{tag}\n"
        return message

    def build_checkall_report(self, *, results: list[dict], viewer_uid: int) -> str:
        success_results = [row for row in results if row["status"] == "success"]
        failed_results = [row for row in results if row["status"] == "failed"]
        others_success = [row for row in success_results if row["owner_uid"] != viewer_uid]
        others_failed = [row for row in failed_results if row["owner_uid"] != viewer_uid]

        report = (
            f"<b>🌍 全局检测结果</b>\n\n"
            f"总计: {len(results)}\n"
            f"✅ 正常: {len(others_success)}\n"
            f"❌ 失效: {len(others_failed)}\n"
            + "—" * 20
            + "\n"
        )

        others_success.sort(key=lambda item: (item["owner_uid"], item["name"]))
        others_failed.sort(key=lambda item: (item["owner_uid"], item["name"]))

        if others_success:
            report += "\n<b>✅ 其他用户当前正常的订阅</b>\n"
            for item in others_success:
                report += (
                    f"\n<b>{html.escape(item['name'])}</b>\n"
                    f"用户: <code>{item['owner_uid']}</code>\n"
                    f"<code>{item['url']}</code>\n"
                )

        if others_failed:
            report += "\n<b>❌ 已失效并自动清理</b>\n"
            for item in others_failed:
                report += (
                    f"\n<b>{html.escape(item['name'])}</b>\n"
                    f"用户: <code>{item['owner_uid']}</code>\n"
                    f"原因：{html.escape(str(item.get('error', '未知'))[:80])}\n"
                )

        if not others_success and not others_failed:
            report += "\n✨ 当前没有其他用户的订阅变动。"

        return report

    def build_usage_audit_report(self, *, limit: int = 20) -> str:
        records = self.usage_audit_service.get_recent_records(limit=limit)
        if not records:
            return "📭 暂无使用审计记录。"

        lines = [f"<b>🧾 最近 {len(records)} 条使用记录</b>\n"]
        for record in reversed(records):
            username = record.get("username")
            full_name = html.escape(record.get("full_name") or "")
            user_label = f"@{html.escape(username)}" if username else full_name or "未知用户"
            lines.append(
                f"⏰ {record.get('ts', '-')}\n"
                f"用户: {user_label} (<code>{record.get('user_id', 0)}</code>)\n"
                f"入口: {html.escape(record.get('source', '-'))}"
            )
            for url in record.get("urls", [])[:10]:
                lines.append(f"<code>{html.escape(url)}</code>")
            if len(record.get("urls", [])) > 10:
                lines.append(f"... 共 {len(record['urls'])} 条链接")
            lines.append("")

        return "\n".join(lines).strip()

    def make_export_file_path(self) -> tuple[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file = os.path.join("data", f"export_{timestamp}.json")
        export_name = f"subscriptions_{timestamp}.json"
        return export_file, export_name
