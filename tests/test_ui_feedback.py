from __future__ import annotations

import unittest
from types import SimpleNamespace

from handlers.callbacks.cache_actions import make_cache_callback_handler
from renderers.formatters import format_node_analysis_compact, format_subscription_compact, format_subscription_info
from shared.format_helpers import get_country_flag
from renderers.telegram_keyboards import build_subscription_keyboard
from services.export_cache_service import ERROR_CACHE_MISSING


class _FakeNotice:
    def __init__(self, text, kwargs):
        self.text = text
        self.kwargs = kwargs

    async def edit_text(self, new_text, **new_kwargs):
        self.text = new_text
        self.kwargs = new_kwargs
        return self


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
    def test_subscription_keyboard_hides_delete_cache_for_normal_user(self):
        keyboard = build_subscription_keyboard(
            "https://example.com/sub",
            lambda action, _url: action,
            enable_latency_tester=True,
            owner_mode=False,
        )
        all_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        self.assertNotIn("删除缓存", all_text)
        self.assertNotIn("删除", all_text)
        self.assertNotIn("标签", "".join(all_text))

    def test_subscription_keyboard_compact_mode_uses_more_ops(self):
        keyboard = build_subscription_keyboard(
            "https://example.com/sub",
            lambda action, _url: action,
            enable_latency_tester=True,
            owner_mode=False,
            compact_user_mode=True,
            user_actions_expanded=False,
        )
        all_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        self.assertIn("更多操作", all_text)
        self.assertFalse(any("导出 YAML" in text for text in all_text))
        self.assertFalse(any("导出 TXT" in text for text in all_text))

    def test_subscription_keyboard_compact_mode_expanded_shows_exports(self):
        keyboard = build_subscription_keyboard(
            "https://example.com/sub",
            lambda action, _url: action,
            enable_latency_tester=True,
            owner_mode=False,
            compact_user_mode=True,
            user_actions_expanded=True,
        )
        all_text = [btn.text for row in keyboard.inline_keyboard for btn in row]
        self.assertTrue(any("导出 YAML" in text for text in all_text))
        self.assertTrue(any("导出 TXT" in text for text in all_text))
        self.assertIn("收起操作", all_text)

    async def test_export_cache_callback_replies_with_success(self):
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
        self.assertEqual(len(update.callback_query.message.documents), 1)
        self.assertGreaterEqual(len(update.callback_query.message.text_replies), 1)

    async def test_export_cache_callback_handles_expired_cache(self):
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
        self.assertIn("缓存", query.answers[-1][0])

    def test_compact_formatter_is_short_and_hides_url(self):
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
        self.assertNotIn("订阅摘要", text)
        self.assertIn("缓存有效", text)
        self.assertIn("最近导出", text)
        self.assertIn("存活：28/40", text)
        self.assertIn("仅抽样", text)
        self.assertNotIn("https://example.com/sub?token=secret", text)

    def test_node_analysis_compact_formatter_uses_node_summary(self):
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
        self.assertIn("存活：7/10", text)
        self.assertNotIn("剩余", text)

    def test_verbose_formatter_uses_expandable_blockquote_fold(self):
        text = format_subscription_info(
            {
                "name": "Wcloud.yaml",
                "node_count": 3,
                "quick_check": {
                    "tested": 3,
                    "alive": 2,
                    "dead": 1,
                    "skipped": 0,
                    "sampled": False,
                    "latency_top": [{"name": "香港01", "latency": 32.4, "type": "ss"}],
                },
                "_raw_nodes": [
                    {"protocol": "ss", "name": "香港01"},
                    {"protocol": "ss", "name": "香港02"},
                    {"protocol": "ss", "name": "新加坡01"},
                ],
            }
        )
        self.assertNotIn("订阅摘要", text)
        self.assertIn("<blockquote>", text)
        self.assertIn("<blockquote expandable>", text)
        self.assertIn("节点列表（共 3 个）", text)
        self.assertIn("快速检测", text)
        self.assertIn("✅ <b>2/3</b> 存活", text)
        self.assertIn("存活率", text)
        self.assertIn("测速 Top（延迟）", text)

    def test_verbose_formatter_collapses_large_node_list(self):
        nodes = [{"protocol": "vmess", "name": f"Node-{i:03d}"} for i in range(1, 401)]
        text = format_subscription_info(
            {
                "name": "Large",
                "node_count": len(nodes),
                "_normalized_nodes": nodes,
            },
            url="https://example.com/sub",
        )
        self.assertIn("<blockquote expandable>", text)
        self.assertIn("节点列表（共 400 个）", text)
        self.assertIn("已折叠", text)
        self.assertLessEqual(len(text), 3900)

    def test_subscription_url_is_in_header_card(self):
        text = format_subscription_info(
            {
                "name": "Demo",
                "node_count": 2,
                "_raw_nodes": [
                    {"protocol": "vmess", "name": "Node-A"},
                    {"protocol": "trojan", "name": "Node-B"},
                ],
            },
            url="https://example.com/sub?token=abc",
        )
        self.assertIn("<blockquote>", text)
        self.assertIn("<blockquote expandable>", text)
        self.assertIn("Demo", text)
        self.assertIn("<code>https://example.com/sub?token=abc</code>", text)
        self.assertLess(text.index("<code>https://example.com/sub?token=abc</code>"), text.index("<b>已用 / 总量：</b>"))

    def test_verbose_formatter_marks_exhausted_when_remaining_is_negative(self):
        text = format_subscription_info(
            {
                "name": "Demo",
                "node_count": 5,
                "used": 2.12 * 1024**4,
                "total": 500 * 1024**3,
                "remaining": -1788804691331,
            }
        )
        self.assertNotIn("<b>订阅状态：</b>", text)
        self.assertIn("<b>剩余流量：</b>", text)

    def test_verbose_formatter_hides_parse_notes(self):
        text = format_subscription_info(
            {
                "name": "Demo",
                "node_count": 2,
                "_content_format": "text",
                "_parse_notes": ["direct-protocol", "base64-decoded"],
                "_raw_nodes": [
                    {"protocol": "trojan", "name": "A01"},
                    {"protocol": "trojan", "name": "A02"},
                ],
            }
        )
        self.assertNotIn("解析备注", text)
        self.assertNotIn("格式=text", text)
        self.assertNotIn("direct-protocol", text)
        self.assertNotIn("协议分布", text)
        self.assertNotIn("地区分布", text)

    def test_verbose_formatter_shows_unknown_usage_when_traffic_missing(self):
        text = format_subscription_info(
            {
                "name": "Demo",
                "node_count": 3,
            }
        )
        self.assertIn("<b>已用 / 总量：</b> 未知 / 未知", text)
        self.assertIn("<b>剩余流量：</b> 未知", text)

    def test_get_country_flag_supports_english_names_and_iso2(self):
        self.assertEqual(get_country_flag("China"), "🇨🇳")
        self.assertEqual(get_country_flag("Japan"), "🇯🇵")
        self.assertEqual(get_country_flag("United States"), "🇺🇸")
        self.assertEqual(get_country_flag("Hong Kong"), "🇭🇰")
        self.assertEqual(get_country_flag("香港"), "🇭🇰")
        self.assertEqual(get_country_flag("美国"), "🇺🇸")
        self.assertEqual(get_country_flag("KR"), "🇰🇷")
        self.assertEqual(get_country_flag("other"), "🌐")


if __name__ == "__main__":
    unittest.main()
