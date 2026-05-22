from __future__ import annotations

import unittest

from services.report_service import build_help_message, build_start_message


class ReportServiceMessageTest(unittest.TestCase):
    def test_start_message_prioritizes_user_main_path(self):
        text = build_start_message(owner_mode=False)

        self.assertIn("发送<b>订阅链接</b>", text)
        self.assertIn("<code>/list</code>", text)
        self.assertIn("<code>/check</code>", text)
        self.assertNotIn("管理员入口", text)

    def test_help_message_explains_check_boundary(self):
        text = build_help_message(owner_mode=False)

        self.assertIn("/check 主要检查订阅状态", text)
        self.assertIn("节点连通性测试是显式操作", text)
        self.assertIn("/deepcheck", text)
        self.assertNotIn("/checkall", text)

    def test_owner_help_keeps_low_frequency_admin_actions_in_web_admin(self):
        text = build_help_message(owner_mode=True)

        self.assertIn("/checkall", text)
        self.assertIn("/backup /restore", text)
        self.assertIn("低频管理动作建议在 Web Admin 中完成", text)
        self.assertNotIn("/usageaudit", text)
        self.assertNotIn("/globallist", text)
        self.assertNotIn("/export /import", text)


if __name__ == "__main__":
    unittest.main()
