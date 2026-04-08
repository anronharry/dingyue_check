from __future__ import annotations

import shutil
import zipfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from handlers.callbacks.subscription_actions import make_subscription_callback_handler
from handlers.messages.documents import make_document_handler, make_node_text_handler


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
            admin_service=SimpleNamespace(
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
        self.assertEqual(query.edits[-1][0], "detail text")

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
            admin_service=SimpleNamespace(
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
        self.assertEqual(query.edits[-1][0], "recent users")

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
            admin_service=SimpleNamespace(
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
        self.assertEqual(query.edits[-1][0], "audit report")

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
            admin_service=SimpleNamespace(
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
        self.assertEqual(query.edits[-1][0], "section:users")

        handled = await handler(update, context, "panel", "listusers")
        self.assertTrue(handled)
        self.assertEqual(query.edits[-1][0], "user list")

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
            admin_service=SimpleNamespace(
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
        self.assertEqual(query.edits[-1][0], "section:maint_backup")
        self.assertEqual(query.edits[-1][1]["reply_markup"], [["panel", {"section": "maintenance"}]])

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
            export_cache_service=SimpleNamespace(get_cache_status=lambda **kwargs: None),
            format_subscription_info=lambda *args, **kwargs: "",
            format_subscription_compact=lambda *args, **kwargs: "",
            format_node_analysis_compact=lambda *args, **kwargs: "",
            make_sub_keyboard=lambda url: None,
            schedule_result_collapse=lambda **kwargs: None,
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
        self.assertIn("Backup restored", update.message.replies[-1].text)
        shutil.rmtree(tmpdir, ignore_errors=True)

    async def test_node_text_handler_schedules_result_collapse(self):
        scheduled = []
        
        class _DocService:
            async def analyze_node_text(self, **kwargs):
                return {"name": "节点列表", "node_count": 3}

        handler = make_node_text_handler(
            document_service=_DocService(),
            format_subscription_info=lambda result: f"verbose:{result['name']}",
            format_node_analysis_compact=lambda result, url=None: f"compact:{result['name']}",
            schedule_result_collapse=lambda **kwargs: scheduled.append(kwargs),
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
        self.assertEqual(len(scheduled), 1)
        self.assertIsNone(scheduled[0]["url"])

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
            export_cache_service=SimpleNamespace(get_cache_status=lambda **kwargs: None),
            format_subscription_info=lambda result, url=None: f"verbose:{result['name']}",
            format_subscription_compact=lambda *args, **kwargs: "",
            format_node_analysis_compact=lambda result, url=None: f"compact:{result['name']}",
            make_sub_keyboard=lambda url: None,
            schedule_result_collapse=lambda **kwargs: None,
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
            admin_service=SimpleNamespace(
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
