from __future__ import annotations

import shutil
import zipfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from handlers.callbacks.subscription_actions import make_subscription_callback_handler
from handlers.messages.documents import make_document_handler, make_node_text_handler
from handlers.messages.router import make_message_handler


class _AdminNS(SimpleNamespace):
    def __getattr__(self, name):
        defaults = {
            "get_owner_panel_data": lambda: {
                "total_subs": 1,
                "expired_subs": 0,
                "authorized_users": 1,
                "public_mode": "OFF",
                "active_24h": 1,
                "recent_profiles": 1,
                "cache_total": 0,
                "cache_valid": 0,
                "exports_24h": 0,
                "recent_exports": 0,
            },
            "get_owner_panel_section_data": lambda _section: {
                "total_subs": 1,
                "expired_subs": 0,
                "authorized_users": 1,
                "public_mode": "OFF",
                "active_24h": 1,
                "cache_total": 0,
                "cache_valid": 0,
            },
            "get_usage_user_counts": lambda **_kwargs: (2, 1),
            "get_usage_audit_summary": lambda mode="others": {
                "mode": mode,
                "title": "others",
                "check_count": 1,
                "user_count": 1,
                "url_count": 1,
                "others_total": 1,
                "owner_total": 0,
                "all_total": 1,
                "top_users": [],
            },
            "get_recent_users_summary": lambda include_owner=False, limit=10: {
                "scope": "all" if include_owner else "others",
                "scope_title": "test",
                "active_24h": 1,
                "authorized_count": 1,
                "rows": [],
            },
            "get_recent_exports_summary": lambda include_owner=False, limit=10: {
                "scope": "all" if include_owner else "others",
                "scope_title": "test",
                "exports_24h": 0,
                "yaml_count": 0,
                "txt_count": 0,
                "rows": [],
            },
            "get_user_list_data": lambda **_kwargs: {"public_mode": "OFF", "users": []},
            "get_globallist_data": lambda **_kwargs: {"rows": []},
        }
        if name in defaults:
            value = defaults[name]
            setattr(self, name, value)
            return value
        raise AttributeError(name)


def _admin_ns(**kwargs):
    return _AdminNS(**kwargs)


class _FakeQuery:
    def __init__(self):
        self.edits = []
        self.answers = []
        self.message = SimpleNamespace(reply_document=self._reply_document)
        self.documents = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs))

    async def _reply_document(self, **kwargs):
        self.documents.append(kwargs)


class _FakeTelegramFile:
    def __init__(self, content: bytes):
        self.content = content

    async def download_as_bytearray(self):
        return bytearray(self.content)


class _FakeDocument:
    def __init__(self, file_name: str, content: bytes, file_size: int | None = None):
        self.file_name = file_name
        self._content = content
        self.file_size = file_size if file_size is not None else len(content)

    async def get_file(self):
        return _FakeTelegramFile(self._content)


class _FakeMessage:
    def __init__(self, document=None):
        self.document = document
        self.replies = []

    async def reply_text(self, text, **kwargs):
        msg = SimpleNamespace(text=text, kwargs=kwargs)

        async def edit_text(new_text, **new_kwargs):
            msg.text = new_text
            msg.kwargs = new_kwargs
            return msg

        async def delete():
            return None

        msg.edit_text = edit_text
        msg.delete = delete
        self.replies.append(msg)
        return msg

    async def delete(self):
        return None


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)


class HandlerIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_audit_detail_callback_edits_message(self):
        query = _FakeQuery()
        handler = make_subscription_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {}, get_by_user=lambda uid: {}),
            is_owner=lambda update: True,
            get_parser=None,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=None,
            admin_service=_admin_ns(
                build_usage_audit_report=lambda **kwargs: ("report", {"mode": "others", "page": 1, "total_pages": 3, "records": [1, 2]}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
            ),
            export_cache_service=None,
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda: [["panel"]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={})
        handled = await handler(update, context, "audit_detail", "others|1|0")
        self.assertTrue(handled)
        self.assertEqual(len(query.edits), 0)
        self.assertTrue(query.answers)
        self.assertTrue(query.answers[-1][1])

    async def test_recent_users_callback_edits_message(self):
        query = _FakeQuery()
        handler = make_subscription_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {}, get_by_user=lambda uid: {}),
            is_owner=lambda update: True,
            get_parser=None,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=None,
            admin_service=_admin_ns(
                build_usage_audit_report=lambda **kwargs: ("report", {"mode": "others", "page": 1, "total_pages": 1, "records": []}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
                build_recent_users_page=lambda **kwargs: ("recent users", {"scope": "others", "page": 1, "total_pages": 2, "records": [1, 2]}),
                build_recent_users_detail=lambda **kwargs: "recent detail",
                build_recent_exports_page=lambda **kwargs: ("recent exports", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_exports_detail=lambda **kwargs: "recent exports detail",
            ),
            export_cache_service=None,
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda: [["panel"]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={})
        handled = await handler(update, context, "recent", "users:others:1")
        self.assertTrue(handled)
        self.assertTrue(query.edits[-1][0])
        self.assertEqual(
            query.edits[-1][1]["reply_markup"],
            {"category": "users", "scope": "others"},
        )

    async def test_owner_panel_callback_routes_to_audit_view(self):
        query = _FakeQuery()
        handler = make_subscription_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {}, get_by_user=lambda uid: {}),
            is_owner=lambda update: True,
            get_parser=None,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=None,
            admin_service=_admin_ns(
                build_usage_audit_report=lambda **kwargs: ("audit report", {"mode": "others", "page": 1, "total_pages": 1, "records": [1]}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
                build_recent_users_page=lambda **kwargs: ("recent users", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_users_detail=lambda **kwargs: "recent detail",
                build_recent_exports_page=lambda **kwargs: ("recent exports", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_exports_detail=lambda **kwargs: "recent exports detail",
                build_owner_panel_text=lambda: "owner panel",
                build_owner_panel_section_text=lambda section: f"section:{section}",
                build_user_list_message=lambda: "user list",
                build_globallist_report=lambda: "global list",
            ),
            export_cache_service=None,
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda **kwargs: [["panel", kwargs]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={})
        handled = await handler(update, context, "panel", "audit")
        self.assertTrue(handled)
        self.assertTrue(query.edits[-1][0])
        self.assertEqual(query.edits[-1][1]["reply_markup"], {"mode": "others"})

    async def test_owner_panel_callback_routes_to_submenu_and_listusers(self):
        query = _FakeQuery()
        handler = make_subscription_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {}, get_by_user=lambda uid: {}),
            is_owner=lambda update: True,
            get_parser=None,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=None,
            admin_service=_admin_ns(
                build_usage_audit_report=lambda **kwargs: ("audit report", {"mode": "others", "page": 1, "total_pages": 1, "records": [1]}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
                build_recent_users_page=lambda **kwargs: ("recent users", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_users_detail=lambda **kwargs: "recent detail",
                build_recent_exports_page=lambda **kwargs: ("recent exports", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_exports_detail=lambda **kwargs: "recent exports detail",
                build_owner_panel_text=lambda: "owner panel",
                build_owner_panel_section_text=lambda section: f"section:{section}",
                build_user_list_message=lambda: "user list",
                build_globallist_report=lambda: "global list",
            ),
            export_cache_service=None,
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda **kwargs: [["panel", kwargs]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={})

        handled = await handler(update, context, "panel", "users")
        self.assertTrue(handled)
        self.assertTrue(query.edits[-1][0])
        self.assertEqual(query.edits[-1][1]["reply_markup"], [["panel", {"section": "users"}]])

        handled = await handler(update, context, "panel", "listusers")
        self.assertTrue(handled)
        self.assertTrue(query.edits[-1][0])

    async def test_owner_panel_callback_routes_to_maintenance_cheatsheet(self):
        query = _FakeQuery()
        handler = make_subscription_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {}, get_by_user=lambda uid: {}),
            is_owner=lambda update: True,
            get_parser=None,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=None,
            admin_service=_admin_ns(
                build_usage_audit_report=lambda **kwargs: ("audit report", {"mode": "others", "page": 1, "total_pages": 1, "records": [1]}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
                build_recent_users_page=lambda **kwargs: ("recent users", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_users_detail=lambda **kwargs: "recent detail",
                build_recent_exports_page=lambda **kwargs: ("recent exports", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_exports_detail=lambda **kwargs: "recent exports detail",
                build_owner_panel_text=lambda: "owner panel",
                build_owner_panel_section_text=lambda section: f"section:{section}",
                build_user_list_message=lambda: "user list",
                build_globallist_report=lambda: "global list",
            ),
            export_cache_service=None,
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda **kwargs: [["panel", kwargs]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={})

        handled = await handler(update, context, "panel", "maint_backup")
        self.assertTrue(handled)
        self.assertTrue(query.edits[-1][0])
        self.assertEqual(query.edits[-1][1]["reply_markup"], [["panel", {"section": "maint_backup"}]])

    async def test_owner_panel_callback_routes_maint_ops_to_dedicated_keyboard(self):
        query = _FakeQuery()
        handler = make_subscription_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {}, get_by_user=lambda uid: {}),
            is_owner=lambda update: True,
            get_parser=None,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=None,
            admin_service=_admin_ns(
                get_usage_user_counts=lambda **kwargs: (2, 1),
                build_usage_audit_report=lambda **kwargs: ("audit report", {"mode": "others", "page": 1, "total_pages": 1, "records": [1]}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
                build_recent_users_page=lambda **kwargs: ("recent users", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_users_detail=lambda **kwargs: "recent detail",
                build_recent_exports_page=lambda **kwargs: ("recent exports", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_exports_detail=lambda **kwargs: "recent exports detail",
                build_owner_panel_text=lambda: "owner panel",
                build_owner_panel_section_text=lambda section: f"section:{section}",
                build_user_list_message=lambda: "user list",
                build_globallist_report=lambda: "global list",
            ),
            access_service=None,
            post_init=None,
            export_cache_service=None,
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda **kwargs: [["panel", kwargs]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={})

        handled = await handler(update, context, "panel", "maint_ops")
        self.assertTrue(handled)
        self.assertTrue(query.edits[-1][0])
        self.assertEqual(query.edits[-1][1]["reply_markup"], [["panel", {"section": "maint_ops"}]])

    async def test_owner_panel_callback_can_toggle_public_access(self):
        query = _FakeQuery()
        access_calls = []
        handler = make_subscription_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {}, get_by_user=lambda uid: {}),
            is_owner=lambda update: True,
            get_parser=None,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=None,
            admin_service=_admin_ns(
                get_usage_user_counts=lambda **kwargs: (2, 1),
                build_owner_panel_text=lambda: "owner panel",
                build_owner_panel_section_text=lambda section: f"section:{section}",
                build_usage_audit_report=lambda **kwargs: ("audit report", {"mode": "others", "page": 1, "total_pages": 1, "records": []}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
                build_recent_users_page=lambda **kwargs: ("recent users", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_users_detail=lambda **kwargs: "recent detail",
                build_recent_exports_page=lambda **kwargs: ("recent exports", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_exports_detail=lambda **kwargs: "recent exports detail",
                build_user_list_message=lambda: "user list",
                build_globallist_report=lambda: "global list",
            ),
            access_service=SimpleNamespace(set_allow_all_users=lambda enabled: (access_calls.append(enabled) or True, True)),
            post_init=None,
            export_cache_service=None,
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda **kwargs: [["panel", kwargs]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={}, application=SimpleNamespace())
        handled = await handler(update, context, "panel", "maint_access_enable")
        self.assertTrue(handled)
        self.assertEqual(access_calls, [True])
        self.assertIn("已开启公开访问模式", query.edits[-1][0])

    async def test_owner_panel_callback_can_send_broadcast_from_panel(self):
        query = _FakeQuery()
        fake_bot = _FakeBot()
        handler = make_subscription_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {}, get_by_user=lambda uid: {}),
            is_owner=lambda update: True,
            get_parser=None,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=None,
            admin_service=_admin_ns(
                get_usage_user_counts=lambda **kwargs: (2, 1),
                build_owner_panel_text=lambda: "owner panel",
                build_owner_panel_section_text=lambda section: f"section:{section}",
                build_usage_audit_report=lambda **kwargs: ("audit report", {"mode": "others", "page": 1, "total_pages": 1, "records": []}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
                build_recent_users_page=lambda **kwargs: ("recent users", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_users_detail=lambda **kwargs: "recent detail",
                build_recent_exports_page=lambda **kwargs: ("recent exports", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_exports_detail=lambda **kwargs: "recent exports detail",
                build_user_list_message=lambda: "user list",
                build_globallist_report=lambda: "global list",
            ),
            access_service=None,
            post_init=None,
            user_manager=SimpleNamespace(get_all=lambda: {11, 22}),
            export_cache_service=None,
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda **kwargs: [["panel", kwargs]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={"pending_owner_broadcast_text": "hello everyone"}, application=SimpleNamespace(), bot=fake_bot)
        handled = await handler(update, context, "panel", "maint_broadcast_send")
        self.assertTrue(handled)
        self.assertEqual(len(fake_bot.sent), 2)
        self.assertIn("广播完成", query.edits[-1][0])
        self.assertNotIn("pending_owner_broadcast_text", context.user_data)

    async def test_document_restore_flow_accepts_zip(self):
        tmpdir = Path("data/test_tmp/test_handler_restore")
        shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr("data/db/users.json", "[1]")
        handler = make_document_handler(
            is_authorized=lambda update: True,
            send_no_permission_msg=lambda update: None,
            input_detector=SimpleNamespace(detect_file_type=lambda name: "unknown"),
            is_owner=lambda update: True,
            owner_only_msg="owner only",
            document_service=None,
            format_subscription_info=lambda *args, **kwargs: "",
            make_sub_keyboard=lambda url, owner_mode=False: None,
            backup_service=SimpleNamespace(restore_backup_bytes=lambda content: ["data/db/users.json"]),
            usage_audit_service=None,
            logger=SimpleNamespace(warning=lambda *a, **k: None, error=lambda *a, **k: None),
        )
        update = SimpleNamespace(
            message=_FakeMessage(document=_FakeDocument("backup.zip", zip_buffer.getvalue())),
            effective_user=SimpleNamespace(id=1),
        )
        context = SimpleNamespace(user_data={"awaiting_restore": True})
        await handler(update, context)
        self.assertIn("恢复完成", update.message.replies[-1].text)
        shutil.rmtree(tmpdir, ignore_errors=True)

    async def test_node_text_handler_sends_verbose_only(self):
        scheduled = []
        
        class _DocService:
            async def analyze_node_text(self, **kwargs):
                return {"name": "节点列表", "node_count": 3}

        handler = make_node_text_handler(
            document_service=_DocService(),
            format_subscription_info=lambda result: f"verbose:{result['name']}",
            logger=SimpleNamespace(warning=lambda *a, **k: None, error=lambda *a, **k: None),
        )
        update = SimpleNamespace(
            message=_FakeMessage(),
            effective_user=SimpleNamespace(id=1),
        )
        update.message.text = "vmess://abc"
        context = SimpleNamespace(job_queue=True)

        await handler(update, context)

        self.assertGreaterEqual(len(update.message.replies), 2)
        self.assertEqual(update.message.replies[-1].text, "verbose:节点列表")
        self.assertEqual(len(scheduled), 0)

    async def test_message_router_handles_owner_broadcast_draft(self):
        handler = make_message_handler(
            is_authorized=lambda update: True,
            send_no_permission_msg=lambda update: None,
            is_owner=lambda update: True,
            get_storage=lambda: SimpleNamespace(),
            input_detector=SimpleNamespace(detect_message_type=lambda update: "other"),
            handle_document=lambda update, context: None,
            handle_subscription=lambda update, context: None,
            handle_node_text=lambda update, context: None,
            tag_forbidden_msg="forbidden",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
        )
        update = SimpleNamespace(
            message=_FakeMessage(),
            effective_user=SimpleNamespace(id=1),
        )
        update.message.text = "broadcast text"
        context = SimpleNamespace(user_data={"awaiting_owner_broadcast": True})

        await handler(update, context)

        self.assertEqual(context.user_data.get("pending_owner_broadcast_text"), "broadcast text")
        self.assertNotIn("awaiting_owner_broadcast", context.user_data)
        self.assertIn("广播草稿已保存", update.message.replies[-1].text)

    async def test_owner_panel_callback_start_import_mode(self):
        query = _FakeQuery()
        handler = make_subscription_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {}, get_by_user=lambda uid: {}),
            is_owner=lambda update: True,
            get_parser=None,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=None,
            admin_service=_admin_ns(
                get_usage_user_counts=lambda **kwargs: (2, 1),
                build_owner_panel_text=lambda: "owner panel",
                build_owner_panel_section_text=lambda section: f"section:{section}",
                build_usage_audit_report=lambda **kwargs: ("audit report", {"mode": "others", "page": 1, "total_pages": 1, "records": []}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
                build_recent_users_page=lambda **kwargs: ("recent users", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_users_detail=lambda **kwargs: "recent detail",
                build_recent_exports_page=lambda **kwargs: ("recent exports", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_exports_detail=lambda **kwargs: "recent exports detail",
                build_user_list_message=lambda: "user list",
                build_globallist_report=lambda: "global list",
            ),
            access_service=None,
            post_init=None,
            user_manager=SimpleNamespace(get_all=lambda: set()),
            export_cache_service=None,
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda **kwargs: [["panel", kwargs]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={}, application=SimpleNamespace(), bot=_FakeBot())
        handled = await handler(update, context, "panel", "maint_import_start")
        self.assertTrue(handled)
        self.assertTrue(context.user_data.get("awaiting_import"))
        self.assertIn("已进入导入模式", query.edits[-1][0])

    async def test_owner_panel_callback_export_json_sends_document(self):
        query = _FakeQuery()

        class _FakeStore:
            def __init__(self, out_path: Path):
                self.out_path = out_path

            def export_to_file(self, file_path: str):
                self.out_path.write_text("{}", encoding="utf-8")
                return True

            @staticmethod
            def get_all():
                return {"u1": {}}

        tmp_file = Path("data/test_tmp/test_panel_export.json")
        tmp_file.parent.mkdir(parents=True, exist_ok=True)
        if tmp_file.exists():
            tmp_file.unlink()
        store = _FakeStore(tmp_file)

        handler = make_subscription_callback_handler(
            get_storage=lambda: store,
            is_owner=lambda update: True,
            get_parser=None,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=None,
            admin_service=_admin_ns(
                get_usage_user_counts=lambda **kwargs: (2, 1),
                build_owner_panel_text=lambda: "owner panel",
                build_owner_panel_section_text=lambda section: f"section:{section}",
                make_export_file_path=lambda: (str(tmp_file), tmp_file.name),
                build_backup_caption=lambda **kwargs: "caption",
                build_usage_audit_report=lambda **kwargs: ("audit report", {"mode": "others", "page": 1, "total_pages": 1, "records": []}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
                build_recent_users_page=lambda **kwargs: ("recent users", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_users_detail=lambda **kwargs: "recent detail",
                build_recent_exports_page=lambda **kwargs: ("recent exports", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_exports_detail=lambda **kwargs: "recent exports detail",
                build_user_list_message=lambda: "user list",
                build_globallist_report=lambda: "global list",
            ),
            access_service=None,
            post_init=None,
            user_manager=SimpleNamespace(get_all=lambda: set()),
            export_cache_service=None,
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda **kwargs: [["panel", kwargs]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={}, application=SimpleNamespace(), bot=_FakeBot())

        handled = await handler(update, context, "panel", "maint_export_json")

        self.assertTrue(handled)
        self.assertEqual(len(query.documents), 1)
        self.assertIn("导出完成", query.edits[-1][0])
        if tmp_file.exists():
            tmp_file.unlink()

    async def test_document_handler_passes_owner_uid_to_document_analysis(self):
        calls = []

        class _DocService:
            @staticmethod
            def extract_subscription_urls(**kwargs):
                return []

            async def analyze_document_nodes(self, **kwargs):
                calls.append(kwargs)
                return {"name": "nodes.txt (节点列表)", "node_count": 1, "_normalized_nodes": [{"name": "HK01"}]}

        handler = make_document_handler(
            is_authorized=lambda update: True,
            send_no_permission_msg=lambda update: None,
            input_detector=SimpleNamespace(detect_file_type=lambda name: "txt"),
            is_owner=lambda update: False,
            owner_only_msg="owner only",
            document_service=_DocService(),
            format_subscription_info=lambda result, url=None: f"verbose:{result['name']}",
            make_sub_keyboard=lambda url, owner_mode=False: None,
            backup_service=SimpleNamespace(),
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            logger=SimpleNamespace(warning=lambda *a, **k: None, error=lambda *a, **k: None),
        )
        update = SimpleNamespace(
            message=_FakeMessage(document=_FakeDocument("nodes.txt", b"vmess://abc")),
            effective_user=SimpleNamespace(id=99),
        )
        context = SimpleNamespace(user_data={})

        await handler(update, context)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["owner_uid"], 99)
        self.assertEqual(calls[0]["file_name"], "nodes.txt")

    async def test_ping_callback_prefers_normalized_nodes_for_latency_test(self):
        calls = []

        async def ping_all_nodes(nodes, concurrency=20):
            calls.append((nodes, concurrency))
            return 1, len(nodes), [{"name": nodes[0]["name"], "latency": 12.3}]

        async def parse(_url):
            return {
                "_raw_nodes": [{"name": "raw-only", "protocol": "vmess"}],
                "_normalized_nodes": [{"name": "HK01", "server": "1.1.1.1", "port": 443, "protocol": "vmess"}],
            }

        async def get_parser():
            return SimpleNamespace(parse=parse)

        query = _FakeQuery()
        query.message = _FakeMessage()
        handler = make_subscription_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {"https://example.com/sub": {"owner_uid": 1}}, get_by_user=lambda uid: {}),
            is_owner=lambda update: True,
            get_parser=get_parser,
            format_subscription_info=None,
            make_sub_keyboard=None,
            cleanup_url_cache=lambda: None,
            url_cache={"hash123": {"url": "https://example.com/sub", "ts": 0}},
            tag_forbidden_msg="forbidden",
            tag_exists_alert="exists",
            confirm_delete_label="confirm",
            inline_keyboard_button=lambda text, callback_data: SimpleNamespace(text=text, callback_data=callback_data),
            inline_keyboard_markup=lambda rows: rows,
            get_short_callback_data=lambda action, url: f"{action}:{url}",
            latency_tester=SimpleNamespace(ping_all_nodes=ping_all_nodes),
            admin_service=_admin_ns(
                build_usage_audit_report=lambda **kwargs: ("audit report", {"mode": "others", "page": 1, "total_pages": 1, "records": []}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
                build_recent_users_page=lambda **kwargs: ("recent users", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_users_detail=lambda **kwargs: "recent detail",
                build_recent_exports_page=lambda **kwargs: ("recent exports", {"scope": "others", "page": 1, "total_pages": 1, "records": []}),
                build_recent_exports_detail=lambda **kwargs: "recent exports detail",
                build_owner_panel_text=lambda: "owner panel",
                build_owner_panel_section_text=lambda section: f"section:{section}",
                build_user_list_message=lambda: "user list",
                build_globallist_report=lambda: "global list",
            ),
            export_cache_service=SimpleNamespace(),
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            build_recent_activity_keyboard=lambda **kwargs: kwargs,
            build_owner_panel_keyboard=lambda **kwargs: [["panel", kwargs]],
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={})

        handled = await handler(update, context, "ping", "hash123")

        self.assertTrue(handled)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][0]["server"], "1.1.1.1")
        self.assertEqual(calls[0][0][0]["port"], 443)

