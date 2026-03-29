from __future__ import annotations

import unittest
from types import SimpleNamespace

from handlers.callbacks.cache_actions import make_cache_callback_handler
from renderers.formatters import format_node_analysis_compact, format_subscription_compact


class _FakeMessage:
    def __init__(self):
        self.text_replies = []
        self.documents = []

    async def reply_text(self, text, **kwargs):
        msg = SimpleNamespace(text=text, kwargs=kwargs)

        async def edit_text(new_text, **new_kwargs):
            msg.text = new_text
            msg.kwargs = new_kwargs
            return msg

        msg.edit_text = edit_text
        self.text_replies.append(msg)
        return msg

    async def reply_document(self, **kwargs):
        self.documents.append(kwargs)


class _FakeQuery:
    def __init__(self):
        self.answers = []
        self.message = _FakeMessage()

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class UIFeedbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_export_cache_callback_replies_with_progress_and_success(self):
        handler = make_cache_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {"https://example.com/sub": {"owner_uid": 1}}),
            is_owner=lambda update: False,
            export_cache_service=SimpleNamespace(
                resolve_export_path=lambda **kwargs: (__file__, None),
                delete_entry=lambda **kwargs: (True, None),
            ),
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
        )
        update = SimpleNamespace(callback_query=_FakeQuery(), effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace()

        handled = await handler(update, context, "export_yaml", "https://example.com/sub")

        self.assertTrue(handled)
        self.assertEqual(update.callback_query.answers[0][0], "正在准备 YAML...")
        self.assertEqual(len(update.callback_query.message.text_replies), 1)
        self.assertIn("YAML 文件已发送", update.callback_query.message.text_replies[0].text)
        self.assertEqual(len(update.callback_query.message.documents), 1)

    async def test_export_cache_callback_blocks_duplicate_clicks_temporarily(self):
        state = {"calls": 0}

        def resolve_export_path(**kwargs):
            state["calls"] += 1
            return __file__, None

        handler = make_cache_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {"https://example.com/sub": {"owner_uid": 1}}),
            is_owner=lambda update: False,
            export_cache_service=SimpleNamespace(
                resolve_export_path=resolve_export_path,
                delete_entry=lambda **kwargs: (True, None),
            ),
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
        )
        query = _FakeQuery()
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace()

        await handler(update, context, "export_txt", "https://example.com/sub")
        await handler(update, context, "export_txt", "https://example.com/sub")

        self.assertGreaterEqual(len(query.answers), 2)
        self.assertEqual(state["calls"], 1)
        self.assertIn("正在处理中", query.answers[-1][0])

    async def test_export_cache_callback_classifies_expired_cache_error(self):
        handler = make_cache_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {"https://example.com/sub": {"owner_uid": 1}}),
            is_owner=lambda update: False,
            export_cache_service=SimpleNamespace(
                resolve_export_path=lambda **kwargs: (None, "缓存不存在或已过期"),
                delete_entry=lambda **kwargs: (True, None),
            ),
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
        )
        query = _FakeQuery()
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace()

        handled = await handler(update, context, "export_yaml", "https://example.com/sub")

        self.assertTrue(handled)
        self.assertIn("缓存已过期", query.answers[-1][0])
        self.assertIn("缓存不存在或已过期", query.message.text_replies[0].text)

    def test_compact_formatter_is_shorter_and_hides_full_url(self):
        text = format_subscription_compact(
            {
                "name": "v1",
                "remaining": 2 * 1024**4,
                "expire_time": "2099-04-26 16:03:46",
                "node_count": 38,
                "_cache_remaining_text": "47小时59分",
                "_cache_last_exported_at": "2026-03-30 00:30:00",
            },
            url="https://example.com/sub?token=secret",
        )
        self.assertIn("订阅简要", text)
        self.assertIn("缓存有效", text)
        self.assertIn("最近导出", text)
        self.assertNotIn("https://example.com/sub?token=secret", text)
        self.assertNotIn("秒", text)

    def test_node_analysis_compact_formatter_uses_node_specific_summary(self):
        text = format_node_analysis_compact(
            {
                "name": "节点列表",
                "node_count": 12,
                "node_stats": {
                    "countries": {"香港": 5, "日本": 4, "美国": 3},
                    "protocols": {"vmess": 6, "trojan": 4, "ss": 2},
                },
            }
        )
        self.assertIn("节点简要", text)
        self.assertIn("节点数", text)
        self.assertIn("地区", text)
        self.assertIn("协议", text)
        self.assertIn("纯节点列表", text)
        self.assertNotIn("<b>剩余：</b>", text)
        self.assertNotIn("<b>到期：</b>", text)


if __name__ == "__main__":
    unittest.main()
