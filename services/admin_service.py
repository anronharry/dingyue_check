"""Owner/admin report builders and export helpers."""
from __future__ import annotations

import html
import os
from datetime import datetime, timedelta


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

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    def _count_recent_profiles(self, profiles: list[dict], *, hours: int = 24) -> int:
        threshold = datetime.now() - timedelta(hours=hours)
        return sum(1 for row in profiles if (self._parse_dt(row.get("last_seen_at")) or datetime.min) >= threshold)

    def _count_recent_records(self, records: list[dict], *, hours: int = 24) -> int:
        threshold = datetime.now() - timedelta(hours=hours)
        return sum(1 for row in records if (self._parse_dt(row.get("ts")) or datetime.min) >= threshold)

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

    def build_owner_panel_text(self) -> str:
        store = self.get_storage()
        total_subscriptions = len(store.get_all())
        total_users = len(self.user_manager.get_all())
        active_profiles = len(self.user_profile_service.get_recent_profiles(limit=1000, include_owner=False))
        cache_entries = len(self.export_cache_service.get_index_snapshot())
        recent_exports = len(
            self.usage_audit_service.query_by_source_prefix(
                prefix="导出缓存:",
                limit=1000,
                owner_id=self.owner_id,
                include_owner=False,
            )
        )
        return (
            "<b>🛠 Owner 控制台</b>\n"
            f"订阅总数: <b>{total_subscriptions}</b>\n"
            f"授权用户: <b>{total_users}</b>\n"
            f"最近活跃用户: <b>{active_profiles}</b>\n"
            f"缓存条目: <b>{cache_entries}</b>\n"
            f"最近导出记录: <b>{recent_exports}</b>\n\n"
            "点击下方按钮进入对应视图。"
        )

    def build_recent_users_report(self, *, limit: int = 10, include_owner: bool = False) -> str:
        report, _ = self.build_recent_users_page(
            include_owner=include_owner,
            page=1,
            page_size=max(1, limit),
        )
        return report

    def build_recent_exports_report(self, *, limit: int = 10, include_owner: bool = False) -> str:
        report, _ = self.build_recent_exports_page(
            include_owner=include_owner,
            page=1,
            page_size=max(1, limit),
        )
        return report

    def build_recent_users_page(self, *, include_owner: bool = False, page: int = 1, page_size: int = 5) -> tuple[str, dict]:
        profiles = self.user_profile_service.get_recent_profiles(limit=1000, include_owner=include_owner)
        total = len(profiles)
        total_pages = max(1, (total + page_size - 1) // page_size)
        safe_page = max(1, min(page, total_pages))
        start = (safe_page - 1) * page_size
        current = profiles[start : start + page_size]
        if not current:
            return "📭 暂无最近活跃用户记录。", {"page": 1, "total_pages": 1, "records": [], "scope": "all" if include_owner else "others"}
        title = "全部用户" if include_owner else "非 Owner 用户"
        lines = [
            "<b>🕘 最近活跃用户</b>",
            f"范围：{title}",
            f"页码：{safe_page} / {total_pages} | 记录数：{total}",
            f"概览：24小时活跃 {self._count_recent_profiles(profiles)} | 已授权 {sum(1 for row in profiles if row.get('is_authorized'))}",
            "",
        ]
        for index, profile in enumerate(current, start=1):
            lines.append(
                f"{index}. {self.user_profile_service.format_user_identity(profile.get('user_id'))}\n"
                f"最后活跃: {profile.get('last_seen_at', '-')}\n"
                f"入口: {html.escape(profile.get('last_source', '-'))}"
            )
            lines.append("")
        return "\n".join(lines).strip(), {
            "page": safe_page,
            "total_pages": total_pages,
            "records": current,
            "scope": "all" if include_owner else "others",
        }

    def build_recent_users_detail(self, *, include_owner: bool = False, page: int = 1, page_size: int = 5, detail_index: int = 0) -> str:
        profiles = self.user_profile_service.get_recent_profiles(limit=1000, include_owner=include_owner)
        total_pages = max(1, (len(profiles) + page_size - 1) // page_size)
        safe_page = max(1, min(page, total_pages))
        start = (safe_page - 1) * page_size
        current = profiles[start : start + page_size]
        if detail_index < 0 or detail_index >= len(current):
            return "❌ 记录不存在或已翻页"
        profile = current[detail_index]
        return (
            "<b>🔎 活跃用户详情</b>\n"
            f"用户: {self.user_profile_service.format_user_identity(profile.get('user_id'))}\n"
            f"首次出现: {profile.get('first_seen_at', '-')}\n"
            f"最后活跃: {profile.get('last_seen_at', '-')}\n"
            f"最近入口: {html.escape(profile.get('last_source', '-'))}\n"
            f"Owner: {'是' if profile.get('is_owner') else '否'}\n"
            f"已授权: {'是' if profile.get('is_authorized') else '否'}"
        )

    def build_recent_exports_page(self, *, include_owner: bool = False, page: int = 1, page_size: int = 5) -> tuple[str, dict]:
        records = self.usage_audit_service.query_by_source_prefix(
            prefix="导出缓存:",
            limit=1000,
            owner_id=self.owner_id,
            include_owner=include_owner,
        )
        total = len(records)
        total_pages = max(1, (total + page_size - 1) // page_size)
        safe_page = max(1, min(page, total_pages))
        start = (safe_page - 1) * page_size
        current = records[start : start + page_size]
        if not current:
            return "📭 暂无最近导出记录。", {"page": 1, "total_pages": 1, "records": [], "scope": "all" if include_owner else "others"}
        title = "全部用户" if include_owner else "非 Owner 用户"
        lines = [
            "<b>📤 最近导出记录</b>",
            f"范围：{title}",
            f"页码：{safe_page} / {total_pages} | 记录数：{total}",
            f"概览：24小时导出 {self._count_recent_records(records)} | YAML {sum(1 for row in records if row.get('source') == '导出缓存:yaml')} | TXT {sum(1 for row in records if row.get('source') == '导出缓存:txt')}",
            "",
        ]
        for index, record in enumerate(current, start=1):
            urls = record.get("urls", [])
            first_url = urls[0] if urls else "-"
            short_url = html.escape(first_url[:80] + ("..." if len(first_url) > 80 else ""))
            fmt = html.escape(record.get("source", "-").split(":", 1)[-1].upper())
            lines.append(
                f"{index}. {self.user_profile_service.format_user_identity(record.get('user_id', 0))}\n"
                f"时间: {record.get('ts', '-')}\n"
                f"格式: {fmt}\n"
                f"目标: <code>{short_url}</code>"
            )
            lines.append("")
        return "\n".join(lines).strip(), {
            "page": safe_page,
            "total_pages": total_pages,
            "records": current,
            "scope": "all" if include_owner else "others",
        }

    def build_recent_exports_detail(self, *, include_owner: bool = False, page: int = 1, page_size: int = 5, detail_index: int = 0) -> str:
        records = self.usage_audit_service.query_by_source_prefix(
            prefix="导出缓存:",
            limit=1000,
            owner_id=self.owner_id,
            include_owner=include_owner,
        )
        total_pages = max(1, (len(records) + page_size - 1) // page_size)
        safe_page = max(1, min(page, total_pages))
        start = (safe_page - 1) * page_size
        current = records[start : start + page_size]
        if detail_index < 0 or detail_index >= len(current):
            return "❌ 记录不存在或已翻页"
        record = current[detail_index]
        urls = record.get("urls", [])
        lines = [
            "<b>🔎 导出记录详情</b>",
            f"用户: {self.user_profile_service.format_user_identity(record.get('user_id', 0))}",
            f"时间: {record.get('ts', '-')}",
            f"格式: {html.escape(record.get('source', '-').split(':', 1)[-1].upper())}",
            f"目标数: {len(urls)}",
            "",
        ]
        for index, url in enumerate(urls, start=1):
            lines.append(f"{index}. <code>{html.escape(url)}</code>")
        return "\n".join(lines).strip()

    def make_export_file_path(self) -> tuple[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file = os.path.join("data", f"export_{timestamp}.json")
        export_name = f"subscriptions_{timestamp}.json"
        return export_file, export_name
