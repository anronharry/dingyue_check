
from __future__ import annotations
import compileall
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bot_async
from scripts.smoke_assembly import assemble_application


class SmokeAssemblyTest(unittest.TestCase):
    def test_compileall(self) -> None:
        self.assertTrue(compileall.compile_dir(str(ROOT), quiet=1))

    def test_import(self) -> None:
        self.assertEqual(bot_async.__name__, "bot_async")

    def test_handler_assembly(self) -> None:
        self.assertEqual(assemble_application(), 24)


if __name__ == "__main__":
    unittest.main()
