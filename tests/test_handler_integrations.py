from __future__ import annotations

import shutil
import zipfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from handlers.callbacks.subscription_actions import make_subscription_callback_handler
from handlers.messages.documents import make_document_handler


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
            usage_audit_service=None,
            admin_service=SimpleNamespace(
                build_usage_audit_report=lambda **kwargs: ("report", {"mode": "others", "page": 1, "total_pages": 3, "records": [1, 2]}),
                build_usage_audit_detail=lambda **kwargs: "detail text",
            ),
            export_cache_service=None,
            build_usage_audit_keyboard=lambda **kwargs: kwargs,
            format_subscription_compact=lambda *args, **kwargs: "",
            schedule_result_collapse=lambda **kwargs: None,
            logger=SimpleNamespace(error=lambda *a, **k: None),
        )
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(user_data={})
        handled = await handler(update, context, "audit_detail", "others|1|0")
        self.assertTrue(handled)
        self.assertEqual(query.edits[-1][0], "detail text")

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
            format_subscription_compact=lambda *args, **kwargs: "",
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
        self.assertIn("恢复完成", update.message.replies[-1].text)
        shutil.rmtree(tmpdir, ignore_errors=True)
