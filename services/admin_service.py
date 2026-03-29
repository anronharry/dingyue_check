"""Owner/admin report builders and export helpers."""
from __future__ import annotations

import html
import os
from datetime import datetime


class AdminService:
    def __init__(
        self,
        *,
        get_storage,
        user_manager,
        owner_id: int,
        format_traffic,
        access_service,
        usage_audit_service,
        user_profile_service,
        export_cache_service,
    ):
        self.get_storage = get_storage
        self.user_manager = user_manager
        self.owner_id = owner_id
        self.format_traffic = format_traffic
        self.access_service = access_service
        self.usage_audit_service = usage_audit_service
        self.user_profile_service = user_profile_service
        self.export_cache_service = export_cache_service

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
            + "—" * 20
            + "\n\n"
        )
        for uid, subs in sorted(others_grouped.items(), key=lambda item: item[0]):
            report += f"🔹 <b>用户 {self.user_profile_service.format_user_identity(uid)}</b>（{len(subs)} 条）\n"
            for url, data in sorted(subs.items(), key=lambda item: item[1].get("name", "未知")):
                cache_entry = self.export_cache_service.get_entry(owner_uid=uid, source=url)
                cache_suffix = f" | 缓存至: {cache_entry.get('expires_at', '-')}" if cache_entry else " | 缓存: 无"
                line = f"  └ <b>{html.escape(data.get('name', '未知'))}</b>"
                if data.get("remaining") is not None:
                    line += f" | 剩余: {self.format_traffic(data.get('remaining', 0))}"
                if data.get("expire_time"):
                    line += f" | 到期: {data['expire_time'][:10]}"
                line += cache_suffix
                line += f"\n    <code>{html.escape(url)}</code>"
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
            suffix = " (Owner)" if self.user_manager.is_owner(uid) else ""
            profile = self.user_profile_service.get_profile(uid) or {}
            seen = profile.get("last_seen_at", "未知")
            source = html.escape(profile.get("last_source", "-"))
            message += f"• {self.user_profile_service.format_user_identity(uid)}{suffix}\n  最后活跃: {seen} | 来源: {source}\n"
        return message

    def build_checkall_report(self, *, results: list[dict], viewer_uid: int) -> str:
        success_results = [row for row in results if row["status"] == "success"]
        failed_results = [row for row in results if row["status"] == "failed"]
        others_success = [row for row in success_results if row["owner_uid"] != viewer_uid]
        others_failed = [row for row in failed_results if row["owner_uid"] != viewer_uid]
        report = (
            "<b>🌍 全局检测结果</b>\n\n"
            f"总计: {len(results)}\n"
            f"✅ 正常: {len(others_success)}\n"
            f"❌ 失效: {len(others_failed)}\n"
            + "—" * 20
            + "\n"
        )
        if others_success:
            report += "\n<b>✅ 其他用户当前正常的订阅</b>\n"
            for item in sorted(others_success, key=lambda row: (row["owner_uid"], row["name"])):
                report += (
                    f"\n<b>{html.escape(item['name'])}</b>\n"
                    f"用户: {self.user_profile_service.format_user_identity(item['owner_uid'])}\n"
                    f"<code>{html.escape(item['url'])}</code>\n"
                )
        if others_failed:
            report += "\n<b>❌ 已失效并自动清理</b>\n"
            for item in sorted(others_failed, key=lambda row: (row["owner_uid"], row["name"])):
                report += (
                    f"\n<b>{html.escape(item['name'])}</b>\n"
                    f"用户: {self.user_profile_service.format_user_identity(item['owner_uid'])}\n"
                    f"原因：{html.escape(str(item.get('error', '未知'))[:80])}\n"
                )
        if not others_success and not others_failed:
            report += "\n✨ 当前没有其他用户的订阅变动。"
        return report

    def build_usage_audit_report(self, *, mode: str = "others", page: int = 1, page_size: int = 5) -> tuple[str, dict]:
        result = self.usage_audit_service.query_records(owner_id=self.owner_id, mode=mode, page=page, page_size=page_size)
        counts = {
            "others": self.usage_audit_service.query_records(owner_id=self.owner_id, mode="others", page=1, page_size=1)["total"],
            "owner": self.usage_audit_service.query_records(owner_id=self.owner_id, mode="owner", page=1, page_size=1)["total"],
            "all": self.usage_audit_service.query_records(owner_id=self.owner_id, mode="all", page=1, page_size=1)["total"],
        }
        if not result["records"]:
            return f"📭 暂无使用审计记录（模式：{html.escape(mode)}）。", result
        title = {"others": "其他用户", "owner": "Owner", "all": "全部用户"}.get(mode, mode)
        lines = [
            "<b>🧾 使用审计</b>",
            f"模式：<b>{title}</b>",
            f"页码：{result['page']} / {result['total_pages']} | 记录数：{result['total']}",
            f"总览：其他 {counts['others']} | Owner {counts['owner']} | 全部 {counts['all']}",
            "",
        ]
        for display_index, record in enumerate(result["records"], start=1):
            urls = record.get("urls", [])
            first_url = urls[0] if urls else "-"
            short_url = html.escape(first_url[:80] + ("..." if len(first_url) > 80 else ""))
            lines.append(
                f"{display_index}. ⏰ {record.get('ts', '-')}\n"
                f"用户: {self.user_profile_service.format_user_identity(record.get('user_id', 0))}\n"
                f"入口: {html.escape(record.get('source', '-'))}\n"
                f"链接数: {len(urls)}\n"
                f"首条: <code>{short_url}</code>"
            )
            lines.append("")
        return "\n".join(lines).strip(), result

    def build_usage_audit_detail(self, *, mode: str, page: int, page_size: int, detail_index: int) -> str:
        result = self.usage_audit_service.query_records(owner_id=self.owner_id, mode=mode, page=page, page_size=page_size)
        if detail_index < 0 or detail_index >= len(result["records"]):
            return "❌ 记录不存在或已翻页"
        record = result["records"][detail_index]
        lines = [
            "<b>🔎 使用审计详情</b>",
            f"时间: {record.get('ts', '-')}",
            f"用户: {self.user_profile_service.format_user_identity(record.get('user_id', 0))}",
            f"入口: {html.escape(record.get('source', '-'))}",
            f"链接数: {len(record.get('urls', []))}",
            "",
        ]
        for index, url in enumerate(record.get("urls", []), start=1):
            lines.append(f"{index}. <code>{html.escape(url)}</code>")
        return "\n".join(lines).strip()

    def build_backup_caption(self, *, zip_name: str) -> str:
        store = self.get_storage()
        return (
            f"✅ 全量备份已生成\n"
            f"文件: <code>{html.escape(zip_name)}</code>\n"
            f"订阅数: {len(store.get_all())}\n"
            f"授权用户: {len(self.user_manager.get_all())}\n"
            f"缓存条目: {len(self.export_cache_service.get_index_snapshot())}"
        )

    def make_export_file_path(self) -> tuple[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file = os.path.join("data", f"export_{timestamp}.json")
        export_name = f"subscriptions_{timestamp}.json"
        return export_file, export_name
