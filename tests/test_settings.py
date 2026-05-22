from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.settings import AppSettings


class AppSettingsTest(unittest.TestCase):
    def test_defaults_disable_redis_memory_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = AppSettings.from_env()

        self.assertFalse(settings.web_admin_redis_allow_memory_fallback)
        self.assertEqual(settings.web_admin_port, 8080)

    def test_bool_parsing_accepts_true_values(self):
        with patch.dict(
            os.environ,
            {
                "ENABLE_WEB_ADMIN": "true",
                "WEB_ADMIN_REDIS_ALLOW_MEMORY_FALLBACK": "1",
            },
            clear=True,
        ):
            settings = AppSettings.from_env()

        self.assertTrue(settings.enable_web_admin)
        self.assertTrue(settings.web_admin_redis_allow_memory_fallback)

    def test_bool_parsing_accepts_false_values(self):
        with patch.dict(os.environ, {"ENABLE_WEB_ADMIN": "off"}, clear=True):
            settings = AppSettings.from_env()

        self.assertFalse(settings.enable_web_admin)

    def test_invalid_bool_names_the_field(self):
        with patch.dict(os.environ, {"ENABLE_WEB_ADMIN": "maybe"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ENABLE_WEB_ADMIN must be a boolean"):
                AppSettings.from_env()

    def test_invalid_allowed_user_id_names_the_field(self):
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": "123,abc"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ALLOWED_USER_IDS must contain only integer"):
                AppSettings.from_env()

    def test_allowed_user_ids_accepts_comma_separated_integers(self):
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": "123, 456"}, clear=True):
            settings = AppSettings.from_env()

        self.assertEqual(settings.allowed_user_ids, {123, 456})

    def test_invalid_int_names_the_field(self):
        with patch.dict(os.environ, {"WEB_ADMIN_PORT": "abc"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "WEB_ADMIN_PORT must be an integer"):
                AppSettings.from_env()

    def test_int_below_minimum_names_the_field(self):
        with patch.dict(os.environ, {"WEB_ADMIN_LOGIN_MAX_ATTEMPTS": "0"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "WEB_ADMIN_LOGIN_MAX_ATTEMPTS must be >= 1"):
                AppSettings.from_env()

    def test_web_admin_port_above_range_names_the_field(self):
        with patch.dict(os.environ, {"WEB_ADMIN_PORT": "70000"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "WEB_ADMIN_PORT must be <= 65535"):
                AppSettings.from_env()


if __name__ == "__main__":
    unittest.main()
