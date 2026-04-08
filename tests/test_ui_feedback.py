from __future__ import annotations

import unittest
from types import SimpleNamespace

from handlers.callbacks.cache_actions import make_cache_callback_handler
from renderers.formatters import format_node_analysis_compact, format_subscription_compact, format_subscription_info
from services.export_cache_service import ERROR_CACHE_MISSING


class _FakeNotice:
    def __init__(self, text, kwargs):
        self.text = text
        self.kwargs = kwargs
        self.deleted = False

    async def edit_text(self, new_text, **new_kwargs):
        self.text = new_text
        self.kwargs = new_kwargs
        return self

    async def delete(self):
        self.deleted = True


class _FakeMessage:
    def __init__(self):
        self.text_replies = []
        self.documents = []

    async def reply_text(self, text, **kwargs):
        msg = _FakeNotice(text, kwargs)
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


class _FakeJobQueue:
    def __init__(self):
        self.jobs = []

    def run_once(self, callback, delay):
        self.jobs.append((callback, delay))


class UIFeedbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_export_cache_callback_replies_with_progress_and_success(self):
        handler = make_cache_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {"https://example.com/sub": {"owner_uid": 1}}),
            is_owner=lambda update: False,
            export_cache_service=SimpleNamespace(
                resolve_export_path=lambda **kwargs: (__file__, None),
                delete_entry=lambda **kwargs: (True, None),
                find_owner_uid_by_source=lambda **kwargs: None,
            ),
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
        )
        update = SimpleNamespace(callback_query=_FakeQuery(), effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(job_queue=_FakeJobQueue())

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
                find_owner_uid_by_source=lambda **kwargs: None,
            ),
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
        )
        query = _FakeQuery()
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(job_queue=None)

        await handler(update, context, "export_txt", "https://example.com/sub")
        await handler(update, context, "export_txt", "https://example.com/sub")

        self.assertGreaterEqual(len(query.answers), 2)
        self.assertEqual(state["calls"], 1)
        self.assertIn("处理中", query.answers[-1][0])

    async def test_export_cache_callback_classifies_expired_cache_error(self):
        handler = make_cache_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {"https://example.com/sub": {"owner_uid": 1}}),
            is_owner=lambda update: False,
            export_cache_service=SimpleNamespace(
                resolve_export_path=lambda **kwargs: (None, ERROR_CACHE_MISSING),
                delete_entry=lambda **kwargs: (True, None),
                find_owner_uid_by_source=lambda **kwargs: None,
            ),
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
        )
        query = _FakeQuery()
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(job_queue=_FakeJobQueue())

        handled = await handler(update, context, "export_yaml", "https://example.com/sub")

        self.assertTrue(handled)
        self.assertIn("缓存不存在或已过期", query.answers[-1][0])
        self.assertIn("缓存不存在或已过期", query.message.text_replies[0].text)

    async def test_delete_cache_callback_replies_immediately_and_supports_owner_uid_fallback(self):
        calls = []
        handler = make_cache_callback_handler(
            get_storage=lambda: SimpleNamespace(get_all=lambda: {}),
            is_owner=lambda update: False,
            export_cache_service=SimpleNamespace(
                resolve_export_path=lambda **kwargs: (__file__, None),
                delete_entry=lambda **kwargs: calls.append(kwargs) or (True, None),
                find_owner_uid_by_source=lambda **kwargs: 9,
            ),
            usage_audit_service=SimpleNamespace(log_check=lambda **kwargs: None),
        )
        query = _FakeQuery()
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=9))
        context = SimpleNamespace(job_queue=_FakeJobQueue())

        handled = await handler(update, context, "delete_cache", "https://example.com/sub")

        self.assertTrue(handled)
        self.assertEqual(query.answers[0][0], "正在删除缓存...")
        self.assertEqual(query.answers[-1][0], "缓存已删除")
        self.assertEqual(calls[0]["owner_uid"], 9)

    def test_compact_formatter_is_shorter_and_hides_full_url(self):
        text = format_subscription_compact(
            {
                "name": "v1",
                "remaining": 2 * 1024**4,
                "expire_time": "2099-04-26 16:03:46",
                "node_count": 38,
                "_cache_remaining_text": "47小时59分钟",
                "_cache_last_exported_at": "2026-03-30 00:30:00",
                "quick_check": {"tested": 40, "alive": 28, "dead": 12, "skipped": 3, "sampled": True},
            },
            url="https://example.com/sub?token=secret",
        )
        self.assertIn("订阅摘要", text)
        self.assertIn("缓存有效", text)
        self.assertIn("最近导出", text)
        self.assertIn("存活：28/40", text)
        self.assertIn("仅抽样检测", text)
        self.assertNotIn("https://example.com/sub?token=secret", text)

    def test_node_analysis_compact_formatter_uses_node_specific_summary(self):
        text = format_node_analysis_compact(
            {
                "name": "节点列表",
                "node_count": 12,
                "quick_check": {"tested": 10, "alive": 7, "dead": 3, "skipped": 2, "sampled": False},
                "node_stats": {
                    "countries": {"香港": 5, "日本": 4, "美国": 3},
                    "protocols": {"vmess": 6, "trojan": 4, "ss": 2},
                },
            }
        )
        self.assertIn("节点摘要", text)
        self.assertIn("节点数", text)
        self.assertIn("地区", text)
        self.assertIn("协议", text)
        self.assertIn("纯节点列表", text)
        self.assertIn("存活：7/10", text)
        self.assertNotIn("剩余", text)
        self.assertNotIn("<b>到期：</b>", text)

    def test_verbose_formatter_renders_node_list_and_quick_check(self):
        text = format_subscription_info(
            {
                "name": "Wcloud.yaml",
                "node_count": 3,
                "quick_check": {"tested": 3, "alive": 2, "dead": 1, "skipped": 0, "sampled": False},
                "_raw_nodes": [
                    {"protocol": "ss", "name": "香港01"},
                    {"protocol": "ss", "name": "香港02"},
                    {"protocol": "ss", "name": "新加坡01"},
                ],
            }
        )
        self.assertIn("节点列表（共 3 个）", text)
        self.assertIn("[SS] 香港01", text)
        self.assertIn("[SS] 新加坡01", text)
        self.assertIn("快速检测", text)
        self.assertIn("已测 3 | 存活 2 | 失败 1", text)


if __name__ == "__main__":
    unittest.main()
