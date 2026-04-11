"""Admin data aggregation service."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from core.models import BatchCheckResult, SubscriptionEntity


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

    def get_globallist_data(self, *, max_users: int = 8, max_subs_per_user: int = 4) -> dict:
        store = self.get_storage()
        grouped = store.get_grouped_by_user()
        others_grouped = {uid: subs for uid, subs in grouped.items() if uid != self.owner_id}
        if not others_grouped:
            return {"rows": []}

        stats = self._get_storage_stats()
        cache_summary = self._summarize_cache_entries()
        total_users = len(others_grouped)
        total_subs = sum(len(subs) for subs in others_grouped.values())
        hidden_users = max(0, total_users - max_users)

        rows: list[dict] = []
        sorted_groups = sorted(others_grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        for uid, subs in sorted_groups[:max_users]:
            subs_rows: list[dict] = []
            sorted_subs = sorted(subs.items(), key=lambda item: item[1].get("name", "未命名"))
            for url, data in sorted_subs[:max_subs_per_user]:
                cache_entry = self.export_cache_service.get_entry(owner_uid=uid, source=url)
                cache_text = "无缓存"
                if cache_entry:
                    cache_text = f"缓存至 {cache_entry.get('expires_at', '-')}"
                subs_rows.append(
                    {
                        "name": data.get("name", "未命名"),
                        "remaining": self.format_traffic(data.get("remaining", 0)) if data.get("remaining") is not None else "-",
                        "expire": (data.get("expire_time") or "-")[:10],
                        "cache": cache_text,
                    }
                )
            rows.append(
                {
                    "uid": uid,
                    "user_text": self.user_profile_service.format_user_identity(uid),
                    "count": len(subs),
                    "subs": subs_rows,
                    "hidden_subs": max(0, len(subs) - max_subs_per_user),
                }
            )

        return {
            "total_users": total_users,
            "total_subs": total_subs,
            "expired": stats.get("expired", 0),
            "valid_cache": cache_summary.get("valid", 0),
            "rows": rows,
            "hidden_users": hidden_users,
        }

    def get_user_list_data(self) -> dict:
        users = self.user_manager.get_all()
        rows = []
        for uid in sorted(users):
            profile = self.user_profile_service.get_profile(uid) or {}
            rows.append(
                {
                    "uid": uid,
                    "identity": self.user_profile_service.format_user_identity(uid),
                    "is_owner": self.user_manager.is_owner(uid),
                    "last_seen": profile.get("last_seen_at", "未知"),
                    "source": str(profile.get("last_source", "-")),
                }
            )
        return {
            "public_mode": "开启" if self.access_service.is_allow_all_users_enabled() else "关闭",
            "users": rows,
        }

    def to_batch_result(self, results: list[SubscriptionEntity | dict]) -> BatchCheckResult:
        entries: list[SubscriptionEntity] = []
        for row in results:
            if isinstance(row, SubscriptionEntity):
                entries.append(row)
                continue
            if row.get("status") == "failed":
                entries.append(
                    SubscriptionEntity.from_failure(
                        url=str(row.get("url") or ""),
                        name=str(row.get("name") or "未知"),
                        error=str(row.get("error") or "未知错误"),
                        owner_uid=row.get("owner_uid"),
                    )
                )
            else:
                entries.append(
                    SubscriptionEntity.from_parse_result(
                        url=str(row.get("url") or ""),
                        result={
                            "name": row.get("name", "未知"),
                            "remaining": row.get("remaining", 0),
                            "expire_time": row.get("expire_time"),
                        },
                        owner_uid=row.get("owner_uid"),
                    )
                )
        return BatchCheckResult(entries=entries)

    def get_usage_audit_summary(self, *, mode: str = "others") -> dict:
        records = self._get_audit_records(limit=self.usage_audit_service.max_read_records)
        counts = {
            "others": self.usage_audit_service.query_records(owner_id=self.owner_id, mode="others", page=1, page_size=1, records=records)["total"],
            "owner": self.usage_audit_service.query_records(owner_id=self.owner_id, mode="owner", page=1, page_size=1, records=records)["total"],
            "all": self.usage_audit_service.query_records(owner_id=self.owner_id, mode="all", page=1, page_size=1, records=records)["total"],
        }
        title = {"others": "其他用户", "owner": "管理员", "all": "全部用户"}.get(mode, "其他用户")
        filtered = self.usage_audit_service.query_records(
            owner_id=self.owner_id,
            mode=mode,
            page=1,
            page_size=max(1, len(records)),
            records=records,
        )["records"]
        threshold = datetime.now() - timedelta(hours=24)
        recent = [row for row in filtered if (self._parse_dt(row.get("ts")) or datetime.min) >= threshold]
        grouped: dict[int, dict] = {}
        for row in recent:
            uid = int(row.get("user_id", 0) or 0)
            item = grouped.setdefault(uid, {"checks": 0, "urls": 0, "uid": uid})
            item["checks"] += 1
            item["urls"] += len(row.get("urls", []) or [])
        top_users = sorted(grouped.values(), key=lambda x: (-x["checks"], x["uid"]))[:8]
        return {
            "mode": mode,
            "title": title,
            "check_count": len(recent),
            "user_count": len(grouped),
            "url_count": sum(item["urls"] for item in grouped.values()),
            "others_total": counts["others"],
            "owner_total": counts["owner"],
            "all_total": counts["all"],
            "top_users": [
                {
                    "identity": self.user_profile_service.format_user_identity(item["uid"]),
                    "checks": item["checks"],
                    "urls": item["urls"],
                }
                for item in top_users
            ],
        }

    def get_recent_users_summary(self, *, include_owner: bool = False, limit: int = 10) -> dict:
        profiles = self.user_profile_service.get_recent_profiles(limit=1000, include_owner=include_owner)
        rows = []
        for profile in profiles[: max(1, limit)]:
            rows.append(
                {
                    "identity": self.user_profile_service.format_user_identity(profile.get("user_id")),
                    "last_seen": profile.get("last_seen_at", "-"),
                    "source": str(profile.get("last_source", "-")),
                }
            )
        return {
            "scope": "all" if include_owner else "others",
            "scope_title": "全部用户" if include_owner else "非管理员用户",
            "active_24h": self._count_recent_profiles(profiles),
            "authorized_count": sum(1 for row in profiles if row.get("is_authorized")),
            "rows": rows,
            "page": 1,
            "total_pages": 1,
        }

    def get_recent_exports_summary(self, *, include_owner: bool = False, limit: int = 10) -> dict:
        audit_records = self._get_audit_records(limit=self.usage_audit_service.max_read_records)
        records = self._get_recent_export_records(include_owner=include_owner, limit=1000, records=audit_records)
        yaml_count = sum(1 for row in records if row.get("source") == f"{EXPORT_AUDIT_PREFIX}yaml")
        txt_count = sum(1 for row in records if row.get("source") == f"{EXPORT_AUDIT_PREFIX}txt")
        rows = []
        for record in records[: max(1, limit)]:
            urls = record.get("urls", [])
            first_url = str(urls[0] if urls else "-")
            rows.append(
                {
                    "identity": self.user_profile_service.format_user_identity(record.get("user_id", 0)),
                    "ts": record.get("ts", "-"),
                    "fmt": str(record.get("source", "-").split(":", 1)[-1].upper()),
                    "target": first_url[:80] + ("..." if len(first_url) > 80 else ""),
                }
            )
        return {
            "scope": "all" if include_owner else "others",
            "scope_title": "全部用户" if include_owner else "非管理员用户",
            "exports_24h": self._count_recent_records(records),
            "yaml_count": yaml_count,
            "txt_count": txt_count,
            "rows": rows,
            "page": 1,
            "total_pages": 1,
        }

    def get_owner_panel_data(self) -> dict:
        stats = self._get_storage_stats()
        recent_profiles = self.user_profile_service.get_recent_profiles(limit=1000, include_owner=False)
        audit_records = self._get_audit_records(limit=self.usage_audit_service.max_read_records)
        recent_exports = self._get_recent_export_records(include_owner=False, limit=1000, records=audit_records)
        cache_summary = self._summarize_cache_entries()
        public_mode = "开启" if self.access_service.is_allow_all_users_enabled() else "关闭"
        return {
            "total_subs": stats.get("total", 0),
            "expired_subs": stats.get("expired", 0),
            "authorized_users": len(self.user_manager.get_all()),
            "public_mode": public_mode,
            "active_24h": self._count_recent_profiles(recent_profiles),
            "recent_profiles": len(recent_profiles),
            "cache_total": cache_summary["total"],
            "cache_valid": cache_summary["valid"],
            "exports_24h": self._count_recent_records(recent_exports),
            "recent_exports": len(recent_exports),
        }

    def get_owner_panel_section_data(self, section: str) -> dict:
        if section == "overview":
            stats = self._get_storage_stats()
            cache_summary = self._summarize_cache_entries()
            return {
                "section": "overview",
                "total_subs": stats.get("total", 0),
                "expired_subs": stats.get("expired", 0),
                "cache_valid": cache_summary["valid"],
                "cache_total": cache_summary["total"],
            }
        if section == "users":
            total_users = len(self.user_manager.get_all())
            recent_profiles = self.user_profile_service.get_recent_profiles(limit=1000, include_owner=False)
            return {
                "section": "users",
                "authorized_users": total_users,
                "active_24h": self._count_recent_profiles(recent_profiles),
            }
        if section == "maintenance":
            public_mode = "开启" if self.access_service.is_allow_all_users_enabled() else "关闭"
            return {"section": "maintenance", "public_mode": public_mode}
        if section == "maint_access":
            public_mode = "开启" if self.access_service.is_allow_all_users_enabled() else "关闭"
            return {"section": "maint_access", "public_mode": public_mode}
        return {"section": section}



    def make_export_file_path(self) -> tuple[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file = os.path.join("data", f"export_{timestamp}.json")
        export_name = f"subscriptions_{timestamp}.json"
        return export_file, export_name

    def build_backup_caption(self, *, zip_name: str) -> str:
        store = self.get_storage()
        return (
            "全量备份已生成\n"
            f"文件: <code>{zip_name}</code>\n"
            f"订阅数: {len(store.get_all())}\n"
            f"授权用户: {len(self.user_manager.get_all())}\n"
            f"缓存条目: {len(self.export_cache_service.get_index_snapshot())}"
        )
