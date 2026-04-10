"""管理员报表与导出辅助工具。"""
from __future__ import annotations

import html
import os
from datetime import datetime, timedelta


EXPORT_AUDIT_PREFIX = "导出缓存:"


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

    def _count_unique_audit_users(
        self,
        records: list[dict],
        *,
        hours: int | None = None,
        include_owner: bool = False,
    ) -> int:
        threshold = datetime.now() - timedelta(hours=hours) if hours and hours > 0 else None
        user_ids: set[int] = set()
        for row in records:
            uid = row.get("user_id")
            if not isinstance(uid, int):
                continue
            if not include_owner and uid == self.owner_id:
                continue
            if threshold is not None:
                ts = self._parse_dt(row.get("ts"))
                if ts is None or ts < threshold:
                    continue
            user_ids.add(uid)
        return len(user_ids)

    def get_usage_user_counts(self, *, include_owner: bool = False) -> tuple[int, int]:
        records = self._get_audit_records(limit=self.usage_audit_service.max_read_records)
        total = self._count_unique_audit_users(records, include_owner=include_owner)
        daily = self._count_unique_audit_users(records, hours=24, include_owner=include_owner)
        return total, daily

    @staticmethod
    def _paginate(items: list[dict], *, page: int, page_size: int) -> tuple[list[dict], int, int]:
        total = len(items)
        total_pages = max(1, (total + page_size - 1) // page_size)
        safe_page = max(1, min(page, total_pages))
        start = (safe_page - 1) * page_size
        return items[start : start + page_size], safe_page, total_pages

    def _get_storage_stats(self) -> dict:
        store = self.get_storage()
        if store is None:
            return {"total": 0, "expired": 0, "active": 0, "total_remaining": 0}
        if hasattr(store, "get_statistics"):
            try:
                return store.get_statistics()
            except Exception:
                pass
        all_subs = store.get_all() if hasattr(store, "get_all") else {}
        total = len(all_subs)
        return {"total": total, "expired": 0, "active": total, "total_remaining": 0}

    def _get_audit_records(self, *, limit: int = 1000) -> list[dict]:
        return list(reversed(self.usage_audit_service.get_recent_records(limit=limit)))

    def _get_recent_export_records(
        self,
        *,
        include_owner: bool = False,
        limit: int = 1000,
        records: list[dict] | None = None,
    ) -> list[dict]:
        return self.usage_audit_service.query_by_source_prefix(
            prefix=EXPORT_AUDIT_PREFIX,
            limit=limit,
            owner_id=self.owner_id,
            include_owner=include_owner,
            records=records,
        )

    def _summarize_cache_entries(self) -> dict:
        snapshot = self.export_cache_service.get_index_snapshot()
        now = datetime.now()
        valid = 0
        recently_exported = 0
        for entry in snapshot.values():
            expires_at = self._parse_dt(entry.get("expires_at"))
            if expires_at and expires_at >= now:
                valid += 1
            last_exported_at = self._parse_dt(entry.get("last_exported_at"))
            if last_exported_at and last_exported_at >= now - timedelta(hours=24):
                recently_exported += 1
        return {
            "total": len(snapshot),
            "valid": valid,
            "expired": max(0, len(snapshot) - valid),
            "recently_exported": recently_exported,
        }

    def build_globallist_report(self, *, max_users: int = 8, max_subs_per_user: int = 4) -> str | None:
        store = self.get_storage()
        grouped = store.get_grouped_by_user()
        others_grouped = {uid: subs for uid, subs in grouped.items() if uid != self.owner_id}
        if not others_grouped:
            return None

        stats = self._get_storage_stats()
        cache_summary = self._summarize_cache_entries()
        total_users = len(others_grouped)
        total_subs = sum(len(subs) for subs in others_grouped.values())
        hidden_users = max(0, total_users - max_users)
        lines = [
            "<b>全局订阅概览</b>",
            f"用户数: <b>{total_users}</b> | 订阅数: <b>{total_subs}</b>",
            f"异常订阅: <b>{stats.get('expired', 0)}</b> | 有效缓存: <b>{cache_summary['valid']}</b>",
            "",
        ]

        sorted_groups = sorted(others_grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        for uid, subs in sorted_groups[:max_users]:
            lines.append(f"<b>{self.user_profile_service.format_user_identity(uid)}</b> | {len(subs)} 条订阅")
            sorted_subs = sorted(subs.items(), key=lambda item: item[1].get("name", "未命名"))
            for url, data in sorted_subs[:max_subs_per_user]:
                cache_entry = self.export_cache_service.get_entry(owner_uid=uid, source=url)
                cache_text = "无缓存"
                if cache_entry:
                    cache_text = f"缓存至 {cache_entry.get('expires_at', '-')}"
                parts = [f"- <b>{html.escape(data.get('name', '未命名'))}</b>"]
                if data.get("remaining") is not None:
                    parts.append(f"剩余 {self.format_traffic(data.get('remaining', 0))}")
                if data.get("expire_time"):
                    parts.append(f"到期 {html.escape(data['expire_time'][:10])}")
                parts.append(cache_text)
                lines.append(" | ".join(parts))
            hidden_subs = max(0, len(subs) - max_subs_per_user)
            if hidden_subs:
                lines.append(f"- 其余 {hidden_subs} 条已折叠，避免消息过长")
            lines.append("")

        if hidden_users:
            lines.append(f"- 其余 {hidden_users} 位用户已折叠，可继续查看最近活跃页")
        return "\n".join(lines).strip()

    def build_user_list_message(self) -> str | None:
        users = self.user_manager.get_all()
        if not users:
            return None
        public_mode = "开启" if self.access_service.is_allow_all_users_enabled() else "关闭"
        lines = [
            "<b>授权用户名单</b>",
            f"公开访问模式: <b>{public_mode}</b>",
            "",
        ]
        for uid in sorted(users):
            suffix = " (管理员)" if self.user_manager.is_owner(uid) else ""
            profile = self.user_profile_service.get_profile(uid) or {}
            seen = profile.get("last_seen_at", "未知")
            source = html.escape(profile.get("last_source", "-"))
            lines.append(f"- {self.user_profile_service.format_user_identity(uid)}{suffix}")
            lines.append(f"  最后活跃: {seen} | 来源: {source}")
        return "\n".join(lines)

    def build_checkall_report(self, *, results: list[dict], viewer_uid: int) -> str:
        success_results = [row for row in results if row["status"] == "success"]
        failed_results = [row for row in results if row["status"] == "failed"]
        others_success = [row for row in success_results if row["owner_uid"] != viewer_uid]
        others_failed = [row for row in failed_results if row["owner_uid"] != viewer_uid]
        lines = [
            "<b>全局检测结果</b>",
            "",
            f"总计: {len(results)}",
            f"正常: {len(others_success)}",
            f"失效: {len(others_failed)}",
            "--------------------",
        ]
        if others_success:
            lines.append("")
            lines.append("<b>当前正常的订阅</b>")
            for item in sorted(others_success, key=lambda row: (row["owner_uid"], row["name"])):
                lines.append(f"<b>{html.escape(item['name'])}</b>")
                lines.append(f"用户: {self.user_profile_service.format_user_identity(item['owner_uid'])}")
                lines.append(f"<code>{html.escape(item['url'])}</code>")
                lines.append("")
        if others_failed:
            lines.append("<b>已失效并自动清理</b>")
            for item in sorted(others_failed, key=lambda row: (row["owner_uid"], row["name"])):
                lines.append(f"<b>{html.escape(item['name'])}</b>")
                lines.append(f"用户: {self.user_profile_service.format_user_identity(item['owner_uid'])}")
                lines.append(f"原因: {html.escape(str(item.get('error', '未知'))[:80])}")
                lines.append("")
        if not others_success and not others_failed:
            lines.append("")
            lines.append("当前没有其他用户的订阅变化。")
        return "\n".join(lines).strip()

    def build_usage_audit_report(self, *, mode: str = "others", page: int = 1, page_size: int = 5, view: str = "time") -> tuple[str, dict]:
        records = self._get_audit_records(limit=self.usage_audit_service.max_read_records)
        counts = {
            "others": self.usage_audit_service.query_records(
                owner_id=self.owner_id,
                mode="others",
                page=1,
                page_size=1,
                records=records,
            )["total"],
            "owner": self.usage_audit_service.query_records(
                owner_id=self.owner_id,
                mode="owner",
                page=1,
                page_size=1,
                records=records,
            )["total"],
            "all": self.usage_audit_service.query_records(
                owner_id=self.owner_id,
                mode="all",
                page=1,
                page_size=1,
                records=records,
            )["total"],
        }
        title = {"others": "其他用户", "owner": "管理员", "all": "全部用户"}.get(mode, mode)
        view = "user" if view == "user" else "time"

        if view == "user":
            filtered = self.usage_audit_service.query_records(
                owner_id=self.owner_id,
                mode=mode,
                page=1,
                page_size=max(1, len(records)),
                records=records,
            )["records"]
            grouped: dict[int, dict] = {}
            for row in filtered:
                uid = int(row.get("user_id", 0) or 0)
                item = grouped.setdefault(
                    uid,
                    {"user_id": uid, "checks": 0, "url_total": 0, "last_ts": "-", "rows": []},
                )
                item["checks"] += 1
                urls = row.get("urls", []) or []
                item["url_total"] += len(urls)
                ts = row.get("ts", "-")
                if ts > item["last_ts"]:
                    item["last_ts"] = ts
                item["rows"].append(row)
            grouped_list = sorted(grouped.values(), key=lambda x: (-x["checks"], x["user_id"]))
            current, safe_page, total_pages = self._paginate(grouped_list, page=page, page_size=page_size)
            if not current:
                paging = {"mode": mode, "view": view, "page": 1, "total_pages": 1, "records": [], "total": 0}
                return f"暂无使用审计记录（模式：{html.escape(mode)}，视图：按用户）。", paging

            def _short_source_label(source: str) -> str:
                source = source.strip()
                if source.startswith("document_import:"):
                    file_name = os.path.basename(source.split(":", 1)[1].strip() or "-")
                    return f"📄 {html.escape(file_name)}"
                if source.startswith("导出缓存:"):
                    return f"📤 {html.escape(source)}"
                return html.escape(source)

            def _is_file_like(value: str) -> bool:
                lower = value.lower()
                return lower.endswith(".yaml") or lower.endswith(".yml") or lower.endswith(".txt") or lower.endswith(".json")

            def _render_log_links(urls: list[str]) -> list[str]:
                lines: list[str] = []
                for raw in urls[:6]:
                    text = str(raw).strip()
                    if not text:
                        continue
                    if _is_file_like(text):
                        lines.append(f"- 📄 {html.escape(os.path.basename(text))}")
                        continue
                    safe = html.escape(text)
                    lines.append(f"- <code>{safe}</code>")
                if len(urls) > 6:
                    lines.append(f"- 其余 {len(urls) - 6} 条已折叠")
                if not lines:
                    lines.append("- 无链接")
                return lines

            lines = [
                "<b>📒 使用审计日志</b>",
                f"筛选: <b>{title}</b> | 视图: <b>按用户</b>",
                f"页码: {safe_page}/{total_pages} | 用户数: {len(grouped_list)}",
                f"总览: 其他用户 {counts['others']} | 管理员 {counts['owner']} | 全部 {counts['all']}",
                "",
            ]
            for idx, item in enumerate(current, start=1):
                detail_entries: list[str] = []
                rows = sorted(item["rows"], key=lambda r: str(r.get("ts", "-")), reverse=True)
                for row in rows[:18]:
                    ts = row.get("ts", "-")
                    source = _short_source_label(str(row.get("source", "-")))
                    urls = row.get("urls", []) or []
                    entry_lines = [f"🕒 {ts} | {source}", "链接："]
                    entry_lines.extend(_render_log_links(urls))
                    detail_entries.append("\n".join(entry_lines))
                if len(rows) > 18:
                    detail_entries.append(f"（其余 {len(rows) - 18} 条日志已折叠）")
                details = "\n\n".join(detail_entries) if detail_entries else "暂无日志"
                lines.append(
                    f"{idx}. {self.user_profile_service.format_user_identity(item['user_id'])} | 检测 <b>{item['checks']}</b> 次 | 链接 <b>{item['url_total']}</b> 条 | 最近 {item['last_ts']}"
                )
                lines.append(f"<blockquote expandable>日志明细\n{details}</blockquote>")
            paging = {
                "mode": mode,
                "view": view,
                "page": safe_page,
                "total_pages": total_pages,
                "records": current,
                "total": len(grouped_list),
            }
            return "\n".join(lines).strip(), paging

        result = self.usage_audit_service.query_records(
            owner_id=self.owner_id,
            mode=mode,
            page=page,
            page_size=page_size,
            records=records,
        )
        if not result["records"]:
            result["view"] = view
            return f"暂无使用审计记录（模式：{html.escape(mode)}，视图：按时间）。", result

        lines = [
            "<b>📒 使用审计日志</b>",
            f"筛选: <b>{title}</b> | 视图: <b>按时间</b>",
            f"页码: {result['page']}/{result['total_pages']} | 记录数: {result['total']}",
            f"总览: 其他用户 {counts['others']} | 管理员 {counts['owner']} | 全部 {counts['all']}",
            "",
        ]
        for display_index, record in enumerate(result["records"], start=1):
            urls = record.get("urls", []) or []
            source = html.escape(str(record.get("source", "-")))
            detail_lines = [f"入口: {source}", "链接列表:"]
            for url in urls[:8]:
                safe_url = html.escape(str(url))
                detail_lines.append(f"- <code>{safe_url}</code>")
            if len(urls) > 8:
                detail_lines.append(f"- 其余 {len(urls) - 8} 条已折叠")
            detail_text = "\n".join(detail_lines)
            lines.append(
                f"{display_index}. {record.get('ts', '-')} | {self.user_profile_service.format_user_identity(record.get('user_id', 0))} | 链接 <b>{len(urls)}</b> 条"
            )
            lines.append(f"<blockquote expandable>{detail_text}</blockquote>")
        result["view"] = view
        return "\n".join(lines).strip(), result

    def build_usage_audit_detail(self, *, mode: str, page: int, page_size: int, detail_index: int) -> str:
        records = self._get_audit_records(limit=self.usage_audit_service.max_read_records)
        result = self.usage_audit_service.query_records(
            owner_id=self.owner_id,
            mode=mode,
            page=page,
            page_size=page_size,
            records=records,
        )
        if detail_index < 0 or detail_index >= len(result["records"]):
            return "记录不存在，或页面已经变化。"
        record = result["records"][detail_index]
        lines = [
            "<b>使用审计详情</b>",
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
            "全量备份已生成\n"
            f"文件: <code>{html.escape(zip_name)}</code>\n"
            f"订阅数: {len(store.get_all())}\n"
            f"授权用户: {len(self.user_manager.get_all())}\n"
            f"缓存条目: {len(self.export_cache_service.get_index_snapshot())}"
        )

    def build_owner_panel_text(self) -> str:
        stats = self._get_storage_stats()
        recent_profiles = self.user_profile_service.get_recent_profiles(limit=1000, include_owner=False)
        audit_records = self._get_audit_records(limit=self.usage_audit_service.max_read_records)
        recent_exports = self._get_recent_export_records(include_owner=False, limit=1000, records=audit_records)
        cache_summary = self._summarize_cache_entries()
        public_mode = "开启" if self.access_service.is_allow_all_users_enabled() else "关闭"
        lines = [
            "<b>管理员控制台</b>",
            f"订阅总数: <b>{stats.get('total', 0)}</b> | 异常订阅: <b>{stats.get('expired', 0)}</b>",
            f"授权用户: <b>{len(self.user_manager.get_all())}</b> | 全员可用: <b>{public_mode}</b>",
            f"24小时活跃用户: <b>{self._count_recent_profiles(recent_profiles)}</b> | 最近活跃记录: <b>{len(recent_profiles)}</b>",
            f"缓存条目: <b>{cache_summary['total']}</b> | 有效缓存: <b>{cache_summary['valid']}</b>",
            f"24小时导出: <b>{self._count_recent_records(recent_exports)}</b> | 最近导出记录: <b>{len(recent_exports)}</b>",
            "",
            "点击下方按钮进入对应视图。",
        ]
        return "\n".join(lines)

    def build_recent_users_report(self, *, limit: int = 10, include_owner: bool = False) -> str:
        report, _ = self.build_recent_users_page(include_owner=include_owner, page=1, page_size=max(1, limit))
        return report

    def build_recent_exports_report(self, *, limit: int = 10, include_owner: bool = False) -> str:
        report, _ = self.build_recent_exports_page(include_owner=include_owner, page=1, page_size=max(1, limit))
        return report

    def build_recent_users_page(self, *, include_owner: bool = False, page: int = 1, page_size: int = 5) -> tuple[str, dict]:
        profiles = self.user_profile_service.get_recent_profiles(limit=1000, include_owner=include_owner)
        current, safe_page, total_pages = self._paginate(profiles, page=page, page_size=page_size)
        scope = "all" if include_owner else "others"
        if not current:
            return "暂无最近活跃用户记录。", {"page": 1, "total_pages": 1, "records": [], "scope": scope}

        title = "全部用户" if include_owner else "非管理员用户"
        lines = [
            "<b>最近活跃用户</b>",
            f"范围: {title}",
            f"页码: {safe_page} / {total_pages} | 记录数: {len(profiles)}",
            f"概览: 24小时活跃 {self._count_recent_profiles(profiles)} | 已授权 {sum(1 for row in profiles if row.get('is_authorized'))}",
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
            "scope": scope,
        }

    def build_recent_users_detail(self, *, include_owner: bool = False, page: int = 1, page_size: int = 5, detail_index: int = 0) -> str:
        profiles = self.user_profile_service.get_recent_profiles(limit=1000, include_owner=include_owner)
        current, _safe_page, _total_pages = self._paginate(profiles, page=page, page_size=page_size)
        if detail_index < 0 or detail_index >= len(current):
            return "记录不存在，或页面已经变化。"
        profile = current[detail_index]
        return (
            "<b>活跃用户详情</b>\n"
            f"用户: {self.user_profile_service.format_user_identity(profile.get('user_id'))}\n"
            f"首次出现: {profile.get('first_seen_at', '-')}\n"
            f"最后活跃: {profile.get('last_seen_at', '-')}\n"
            f"最近入口: {html.escape(profile.get('last_source', '-'))}\n"
            f"管理员: {'是' if profile.get('is_owner') else '否'}\n"
            f"已授权: {'是' if profile.get('is_authorized') else '否'}"
        )

    def build_recent_exports_page(self, *, include_owner: bool = False, page: int = 1, page_size: int = 5) -> tuple[str, dict]:
        audit_records = self._get_audit_records(limit=self.usage_audit_service.max_read_records)
        records = self._get_recent_export_records(include_owner=include_owner, limit=1000, records=audit_records)
        current, safe_page, total_pages = self._paginate(records, page=page, page_size=page_size)
        scope = "all" if include_owner else "others"
        if not current:
            return "暂无最近导出记录。", {"page": 1, "total_pages": 1, "records": [], "scope": scope}

        title = "全部用户" if include_owner else "非管理员用户"
        yaml_count = sum(1 for row in records if row.get("source") == f"{EXPORT_AUDIT_PREFIX}yaml")
        txt_count = sum(1 for row in records if row.get("source") == f"{EXPORT_AUDIT_PREFIX}txt")
        lines = [
            "<b>最近导出记录</b>",
            f"范围: {title}",
            f"页码: {safe_page} / {total_pages} | 记录数: {len(records)}",
            f"概览: 24小时导出 {self._count_recent_records(records)} | YAML {yaml_count} | TXT {txt_count}",
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
            "scope": scope,
        }

    def build_recent_exports_detail(self, *, include_owner: bool = False, page: int = 1, page_size: int = 5, detail_index: int = 0) -> str:
        audit_records = self._get_audit_records(limit=self.usage_audit_service.max_read_records)
        records = self._get_recent_export_records(include_owner=include_owner, limit=1000, records=audit_records)
        current, _safe_page, _total_pages = self._paginate(records, page=page, page_size=page_size)
        if detail_index < 0 or detail_index >= len(current):
            return "记录不存在，或页面已经变化。"
        record = current[detail_index]
        urls = record.get("urls", [])
        lines = [
            "<b>导出记录详情</b>",
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

    def build_owner_panel_section_text(self, section: str) -> str:
        if section == "overview":
            stats = self._get_storage_stats()
            cache_summary = self._summarize_cache_entries()
            return "\n".join(
                [
                    "<b>管理员控制台 / 总览</b>",
                    f"订阅总数: <b>{stats.get('total', 0)}</b>",
                    f"异常订阅: <b>{stats.get('expired', 0)}</b>",
                    f"有效缓存: <b>{cache_summary['valid']}</b> / {cache_summary['total']}",
                    "",
                    "这里集中展示整体运行健康状态。",
                ]
            )
        if section == "users":
            total_users = len(self.user_manager.get_all())
            recent_profiles = self.user_profile_service.get_recent_profiles(limit=1000, include_owner=False)
            return "\n".join(
                [
                    "<b>管理员控制台 / 用户</b>",
                    f"授权用户: <b>{total_users}</b>",
                    f"24小时活跃: <b>{self._count_recent_profiles(recent_profiles)}</b>",
                    "",
                    "这里集中查看活跃用户和授权名单。",
                ]
            )
        if section == "maintenance":
            public_mode = "开启" if self.access_service.is_allow_all_users_enabled() else "关闭"
            return "\n".join(
                [
                    "<b>管理员控制台 / 维护</b>",
                    f"公开访问: <b>{public_mode}</b>",
                    "",
                    "低频维护操作已收纳在下方子页面。",
                    "需要执行时仍建议直接使用命令。",
                ]
            )
        if section == "maint_backup":
            return "\n".join(
                [
                    "<b>管理员控制台 / 备份迁移</b>",
                    "",
                    "常用命令：",
                    "<code>/backup</code> 生成完整备份 ZIP",
                    "<code>/restore</code> 从 ZIP 恢复完整状态",
                    "<code>/export</code> 导出订阅 JSON",
                    "<code>/import</code> 导入订阅 JSON",
                    "",
                    "推荐顺序：先 /backup，再到新环境 /restore。",
                ]
            )
        if section == "maint_access":
            public_mode = "开启" if self.access_service.is_allow_all_users_enabled() else "关闭"
            return "\n".join(
                [
                    "<b>管理员控制台 / 权限开关</b>",
                    f"当前公开访问: <b>{public_mode}</b>",
                    "",
                    "常用命令：",
                    "<code>/adduser &lt;id&gt;</code> 授权用户",
                    "<code>/deluser &lt;id&gt;</code> 取消授权",
                    "<code>/allowall</code> 开启公开访问",
                    "<code>/denyall</code> 恢复授权模式",
                ]
            )
        if section == "maint_ops":
            return "\n".join(
                [
                    "<b>管理员控制台 / 维护命令</b>",
                    "",
                    "低频但重要：",
                    "<code>/broadcast 内容</code> 广播通知",
                    "<code>/checkall</code> 全局检测所有订阅",
                    "<code>/refresh_menu</code> 刷新命令菜单",
                    "<code>/ownerpanel</code> 重新打开控制台",
                ]
            )
        return self.build_owner_panel_text()
